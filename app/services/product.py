import uuid
from typing import List
from loguru import logger
from sqlmodel import Session, select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, BackgroundTasks

from app.db.schema import (
    User, Tenant, TenantType,
    Product, ProductMedia, ProductVersion, ProductVersionStatus,
    AuditAction, ProductContributionRequest, CollaborationComment, ConnectionStatus, SupplierProfile, RequestStatus,
    ProductVersionMaterial, ProductVersionSupplyNode, ProductVersionCertificate, TenantConnection
)

from app.models.product import (
    ProductCreate, ProductIdentityUpdate, ProductRead,
    ProductMediaAdd, ProductMediaRead, ProductMediaReorder, ProductAssignmentRequest,
    ProductVersionDetailRead, ProductMaterialRead,
    ProductSupplyNodeRead, ProductCertificateRead,
    ProductCollaborationStatusRead
)
from app.utils.file_storage import save_base64_image
from app.core.audit import _perform_audit_log


class ProductService:
    def __init__(self, session: Session):
        self.session = session

    def _get_brand_tenant(self, user: User) -> Tenant:
        """Enforce Brand Access Only."""
        tenant_id = getattr(user, "_tenant_id", None)
        tenant = self.session.get(Tenant, tenant_id)
        if not tenant or tenant.type != TenantType.BRAND:
            raise HTTPException(
                403, "Only Brands can manage Product Identity.")
        return tenant

    # ==========================
    # READ OPERATIONS
    # ==========================

    def list_products(self, user: User) -> List[ProductRead]:
        """
        Lists all products for the Brand.
        Computed fields:
        - latest_version_id/name: derived from the sequence.
        - main_image_url: from the cache field.
        """
        brand = self._get_brand_tenant(user)

        # Eager load versions and media to avoid N+1 queries
        statement = (
            select(Product)
            .where(Product.tenant_id == brand.id)
            .options(selectinload(Product.technical_versions))
            .options(selectinload(Product.marketing_media))
            .order_by(Product.created_at.desc())
        )
        products = self.session.exec(statement).all()

        results = []
        for p in products:
            # Determine Active Version Name
            v_id = None
            v_name = p.pending_version_name  # Default to pending

            if p.technical_versions:
                # If real versions exist, show the latest
                latest_v = sorted(
                    p.technical_versions, key=lambda v: v.version_sequence, reverse=True)[0]
                v_id = latest_v.id
                v_name = latest_v.version_name

            # Build Read Model
            results.append(ProductRead(
                id=p.id,
                sku=p.sku,
                name=p.name,
                description=p.description,
                ean=p.ean,
                upc=p.upc,
                lifecycle_status=p.lifecycle_status,
                main_image_url=p.main_image_url,
                latest_version_id=v_id,
                latest_version_name=v_name,
                media=[],
                created_at=p.created_at,
                updated_at=p.updated_at
            ))
        return results

    def get_product(self, user: User, product_id: uuid.UUID) -> ProductRead:
        """Get single product details with full media gallery."""
        brand = self._get_brand_tenant(user)

        product = self.session.exec(
            select(Product)
            .where(Product.id == product_id, Product.tenant_id == brand.id)
            .options(selectinload(Product.technical_versions))
            .options(selectinload(Product.marketing_media))
        ).first()

        if not product:
            raise HTTPException(404, "Product not found.")

        # Latest version logic
        latest_v = None
        if product.technical_versions:
            latest_v = sorted(product.technical_versions,
                              key=lambda v: v.version_sequence, reverse=True)[0]

        # Map Media
        # Sort media by display_order
        sorted_media = sorted(product.marketing_media,
                              key=lambda m: m.display_order)
        media_dtos = [
            ProductMediaRead(
                id=m.id,
                file_url=m.file_url,
                file_name=m.file_name,
                file_type=m.file_type,
                display_order=m.display_order,
                is_main=m.is_main,
                description=m.description
            ) for m in sorted_media
        ]

        return ProductRead(
            id=product.id,
            sku=product.sku,
            name=product.name,
            description=product.description,
            ean=product.ean,
            upc=product.upc,
            lifecycle_status=product.lifecycle_status,
            main_image_url=product.main_image_url,
            latest_version_id=latest_v.id if latest_v else None,
            latest_version_name=latest_v.version_name if latest_v else None,
            media=media_dtos,
            created_at=product.created_at,
            updated_at=product.updated_at
        )

    def create_product(self, user: User, data: ProductCreate, background_tasks: BackgroundTasks) -> ProductRead:
        """
        1. Creates Product Shell.
        2. Creates Initial Version (Empty, Draft) with Brand-provided name.
        3. Saves and Links Media.
        4. Audits ALL entities created.
        """
        brand = self._get_brand_tenant(user)

        # 1. Uniqueness Check
        if self.session.exec(select(Product).where(Product.tenant_id == brand.id, Product.sku == data.sku)).first():
            raise HTTPException(
                409, f"Product SKU '{data.sku}' already exists.")

        try:
            # 1. Create Shell (With Pending Name)
            product = Product(
                tenant_id=brand.id,
                sku=data.sku,
                name=data.name,
                description=data.description,
                ean=data.ean,
                upc=data.upc,
                internal_erp_id=data.internal_erp_id,
                lifecycle_status=data.lifecycle_status,
                pending_version_name=data.initial_version_name
            )
            self.session.add(product)
            self.session.flush()  # Get ID

            # Audit Product
            background_tasks.add_task(
                _perform_audit_log, tenant_id=brand.id, user_id=user.id,
                entity_type="Product", entity_id=product.id,
                action=AuditAction.CREATE, changes=data.model_dump(
                    exclude={"media_files"})
            )

            # 2. Handle Media
            main_url = None
            media_responses = []

            for idx, media_item in enumerate(data.media_files):
                # 1. Save File
                file_url = save_base64_image(media_item.file_data)

                # 2. DB Record
                media_entry = ProductMedia(
                    product_id=product.id,
                    file_url=file_url,
                    file_name=media_item.file_name,
                    file_type=media_item.file_type,
                    description=media_item.description,
                    is_main=media_item.is_main,
                    display_order=idx
                )
                self.session.add(media_entry)
                self.session.flush()

                if media_item.is_main:
                    main_url = file_url

                # Audit Media Creation
                background_tasks.add_task(
                    _perform_audit_log, tenant_id=brand.id, user_id=user.id,
                    entity_type="ProductMedia", entity_id=media_entry.id,
                    action=AuditAction.CREATE, changes={
                        "file_name": media_item.file_name}
                )

                # Prepare response object
                media_responses.append(ProductMediaRead(
                    id=media_entry.id,
                    file_url=file_url,
                    file_name=media_entry.file_name,
                    file_type=media_entry.file_type,
                    display_order=media_entry.display_order,
                    is_main=media_entry.is_main,
                    description=media_entry.description
                ))

            # Update cache field
            if main_url:
                product.main_image_url = main_url
                self.session.add(product)

            self.session.commit()
            self.session.refresh(product)

            return ProductRead(
                id=product.id,
                sku=product.sku,
                name=product.name,
                description=product.description,
                ean=product.ean,
                upc=product.upc,
                lifecycle_status=product.lifecycle_status,
                main_image_url=product.main_image_url,
                latest_version_id=None,
                latest_version_name=product.pending_version_name,
                media=media_responses,
                created_at=product.created_at,
                updated_at=product.updated_at
            )

        except Exception as e:
            self.session.rollback()
            logger.error(f"Create Product Failed: {e}")
            raise HTTPException(500, "Failed to create product.")

    # ==========================
    # IDENTITY MANAGEMENT
    # ==========================

    def update_product_identity(self, user: User, product_id: uuid.UUID, data: ProductIdentityUpdate, background_tasks: BackgroundTasks):
        brand = self._get_brand_tenant(user)
        product = self.session.get(Product, product_id)

        if not product or product.tenant_id != brand.id:
            raise HTTPException(404, "Product not found.")

        old_state = product.model_dump()

        if data.name:
            product.name = data.name
        if data.description:
            product.description = data.description
        if data.ean:
            product.ean = data.ean
        if data.upc:
            product.upc = data.upc
        if data.lifecycle_status:
            product.lifecycle_status = data.lifecycle_status

        self.session.add(product)
        self.session.commit()

        # Audit
        background_tasks.add_task(
            _perform_audit_log, tenant_id=brand.id, user_id=user.id,
            entity_type="Product", entity_id=product.id,
            action=AuditAction.UPDATE,
            changes={"old": old_state,
                     "new": data.model_dump(exclude_unset=True)}
        )
        return product

    # ==========================
    # MEDIA MANAGEMENT (Granular)
    # ==========================

    def add_media(self, user: User, product_id: uuid.UUID, data: ProductMediaAdd, background_tasks: BackgroundTasks):
        brand = self._get_brand_tenant(user)
        product = self.session.get(Product, product_id)
        if not product or product.tenant_id != brand.id:
            raise HTTPException(404, "Product not found.")

        # If setting as main, unset others first
        if data.is_main:
            self._unset_main_media(product.id)

        # Save Base64
        file_url = save_base64_image(data.file_data)

        # Determine order (append to end)
        current_max = self.session.exec(select(ProductMedia).where(
            ProductMedia.product_id == product.id)).all()
        next_order = len(current_max)

        media = ProductMedia(
            product_id=product.id,
            file_url=file_url,
            file_name=data.file_name,
            file_type=data.file_type,
            description=data.description,
            is_main=data.is_main,
            display_order=next_order
        )

        self.session.add(media)

        if data.is_main:
            product.main_image_url = file_url
            self.session.add(product)

        self.session.commit()
        self.session.refresh(media)

        # Audit
        background_tasks.add_task(
            _perform_audit_log, tenant_id=brand.id, user_id=user.id,
            entity_type="ProductMedia", entity_id=media.id,
            action=AuditAction.CREATE, changes={"file_name": data.file_name}
        )
        return media

    def delete_media(self, user: User, media_id: uuid.UUID, background_tasks: BackgroundTasks):
        brand = self._get_brand_tenant(user)
        media = self.session.get(ProductMedia, media_id)

        if not media:
            raise HTTPException(404, "Media not found.")

        # Verify ownership via Product linkage
        product = self.session.get(Product, media.product_id)
        if product.tenant_id != brand.id:
            raise HTTPException(403, "Access denied.")

        was_main = media.is_main
        file_name = media.file_name

        self.session.delete(media)

        # If deleted main, update product cache to None (or could pick next available)
        if was_main:
            product.main_image_url = None
            self.session.add(product)

        self.session.commit()

        # Audit
        background_tasks.add_task(
            _perform_audit_log, tenant_id=brand.id, user_id=user.id,
            entity_type="ProductMedia", entity_id=media_id,
            action=AuditAction.DELETE, changes={"file_name": file_name}
        )
        return {"message": "Media deleted"}

    def set_main_media(self, user: User, product_id: uuid.UUID, media_id: uuid.UUID, background_tasks: BackgroundTasks):
        """Sets a specific image as Main, updates Product cache."""
        brand = self._get_brand_tenant(user)
        media = self.session.get(ProductMedia, media_id)

        if not media:
            raise HTTPException(404, "Media not found.")
        if media.product_id != product_id:
            raise HTTPException(400, "Media does not belong to this product.")

        # Unset all
        self._unset_main_media(product_id)

        # Set new
        media.is_main = True
        self.session.add(media)

        # Update Product Cache
        product = self.session.get(Product, product_id)
        product.main_image_url = media.file_url
        self.session.add(product)

        self.session.commit()

        # Audit
        background_tasks.add_task(
            _perform_audit_log, tenant_id=brand.id, user_id=user.id,
            entity_type="Product", entity_id=product_id,
            action=AuditAction.UPDATE, changes={
                "action": "set_main_image", "media_id": str(media_id)}
        )
        return {"message": "Main image updated"}

    def reorder_media(self, user: User, product_id: uuid.UUID, order_list: List[ProductMediaReorder], background_tasks: BackgroundTasks):
        """Bulk update display_order."""
        brand = self._get_brand_tenant(user)

        # Verify Product Ownership
        product = self.session.get(Product, product_id)
        if not product or product.tenant_id != brand.id:
            raise HTTPException(403, "Access denied.")

        for item in order_list:
            media = self.session.get(ProductMedia, item.media_id)
            if media and media.product_id == product_id:
                media.display_order = item.new_order
                self.session.add(media)

        self.session.commit()

        # Audit
        background_tasks.add_task(
            _perform_audit_log, tenant_id=brand.id, user_id=user.id,
            entity_type="Product", entity_id=product_id,
            action=AuditAction.UPDATE, changes={
                "action": "reorder_media", "count": len(order_list)}
        )
        return {"message": "Media reordered"}

    def _unset_main_media(self, product_id: uuid.UUID):
        """Helper to set is_main=False for all media of a product."""
        existing = self.session.exec(
            select(ProductMedia)
            .where(ProductMedia.product_id == product_id)
            .where(ProductMedia.is_main == True)
        ).all()
        for img in existing:
            img.is_main = False
            self.session.add(img)

    def assign_product(
        self,
        user: User,
        product_id: uuid.UUID,
        data: ProductAssignmentRequest,
        background_tasks: BackgroundTasks
    ):
        """
        Assigns a Product to a Supplier.
        Safe against duplicate active requests.
        """
        brand = self._get_brand_tenant(user)

        # 1. Fetch Product
        product = self.session.get(Product, product_id)
        if not product or product.tenant_id != brand.id:
            raise HTTPException(404, "Product not found.")

        # 2. Fetch Supplier Profile & Verify Connection
        profile = self.session.get(SupplierProfile, data.supplier_profile_id)
        if not profile or profile.tenant_id != brand.id:
            raise HTTPException(404, "Supplier profile not found.")

        connection = profile.connection
        if not connection:
            raise HTTPException(
                400, "This supplier is not connected on the platform.")
        if connection.status != ConnectionStatus.ACTIVE:
            raise HTTPException(
                400, "Cannot assign: Connection is not active.")
        if not connection.supplier_tenant_id:
            raise HTTPException(
                400, "Cannot assign: Supplier has not completed onboarding (No Tenant ID).")

        real_supplier_id = connection.supplier_tenant_id

        # 3. Handle Version Strategy
        existing_versions = self.session.exec(
            select(ProductVersion)
            .where(ProductVersion.product_id == product.id)
            .order_by(ProductVersion.version_sequence.desc())
        ).all()

        target_version = None

        if not existing_versions:
            # SCENARIO A: First Assignment
            v_name = product.pending_version_name or "Initial Version"
            target_version = ProductVersion(
                product_id=product.id,
                supplier_tenant_id=real_supplier_id,
                version_sequence=1,
                version_name=v_name,
                status=ProductVersionStatus.DRAFT
            )
            self.session.add(target_version)
            product.pending_version_name = None
            self.session.add(product)
            self.session.flush()

        else:
            latest = existing_versions[0]

            if latest.status in [ProductVersionStatus.APPROVED, ProductVersionStatus.SUBMITTED]:
                # SCENARIO B: Locked -> Clone new Draft
                target_version = self._clone_version_helper(latest)
                target_version.supplier_tenant_id = real_supplier_id
                target_version.version_sequence = latest.version_sequence + 1
                target_version.status = ProductVersionStatus.DRAFT
                self.session.add(target_version)
                self.session.flush()
            else:
                # SCENARIO C: Existing Draft
                # If we are re-assigning to a DIFFERENT supplier, update the ownership
                if latest.supplier_tenant_id != real_supplier_id:
                    latest.supplier_tenant_id = real_supplier_id
                    self.session.add(latest)
                target_version = latest

        # =========================================================
        # INTEGRITY GUARD: PREVENT DUPLICATE ACTIVE REQUESTS
        # =========================================================
        # We only block if the status implies "Work is Happening".
        # We DO NOT block if status is 'declined' (because we want to retry).
        active_statuses = [
            RequestStatus.SENT,
            RequestStatus.ACCEPTED,
            RequestStatus.IN_PROGRESS,
            RequestStatus.CHANGES_REQUESTED,
            RequestStatus.SUBMITTED
        ]

        # Check if there is already an open request for this specific version ID
        existing_active_request = self.session.exec(
            select(ProductContributionRequest)
            .where(ProductContributionRequest.current_version_id == target_version.id)
            .where(ProductContributionRequest.status.in_(active_statuses))
        ).first()

        if existing_active_request:
            # If the user is trying to "re-send" to the SAME supplier who hasn't responded yet,
            # we might just want to update the note/due date instead of erroring?
            # Or strictly fail. Let's strictly fail to keep state clean.
            raise HTTPException(
                400,
                f"Cannot assign: An active request ({existing_active_request.status}) is already pending for this version."
            )
        # =========================================================

        # 4. Create Workflow Request
        request = ProductContributionRequest(
            connection_id=connection.id,
            brand_tenant_id=brand.id,
            supplier_tenant_id=real_supplier_id,
            initial_version_id=target_version.id,
            current_version_id=target_version.id,
            due_date=data.due_date,
            request_note=data.request_note,
            status=RequestStatus.SENT
        )
        self.session.add(request)

        # Add Note as Comment History
        if data.request_note:
            comment = CollaborationComment(
                request_id=request.id,
                author_user_id=user.id,
                body=data.request_note
            )
            self.session.add(comment)

        self.session.commit()
        self.session.refresh(request)

        # 5. Audit
        background_tasks.add_task(
            _perform_audit_log,
            tenant_id=brand.id,
            user_id=user.id,
            entity_type="ProductContributionRequest",
            entity_id=request.id,
            action=AuditAction.CREATE,
            changes={
                "product_id": str(product.id),
                "supplier_profile_id": str(profile.id),
                "version_sequence": target_version.version_sequence
            }
        )

        return {"message": "Assignment sent successfully", "request_id": request.id}

    def _clone_version_helper(self, source: ProductVersion) -> ProductVersion:
        """Helper to copy structure without ID/Relationships."""
        return ProductVersion(
            product_id=source.product_id,
            version_name=source.version_name,  # Usually overwritten by caller
            manufacturing_country=source.manufacturing_country,
            mass_kg=source.mass_kg,
            total_carbon_footprint=source.total_carbon_footprint,
            total_energy_mj=source.total_energy_mj,
            total_water_usage=source.total_water_usage,
        )

    # ==========================
    # TECHNICAL DATA
    # ==========================

    def get_latest_version_detail(self, user: User, product_id: uuid.UUID) -> ProductVersionDetailRead:
        """
        Fetches the full technical data for the LATEST active version of a product.
        """
        brand = self._get_brand_tenant(user)

        # 1. Verify Ownership
        product = self.session.get(Product, product_id)
        if not product or product.tenant_id != brand.id:
            raise HTTPException(404, "Product not found.")

        # 2. Get Latest Version with Eager Loading
        statement = (
            select(ProductVersion)
            .where(ProductVersion.product_id == product_id)
            .order_by(ProductVersion.version_sequence.desc())
            .limit(1)
            .options(
                selectinload(ProductVersion.materials),
                selectinload(ProductVersion.supply_chain),
                selectinload(ProductVersion.certificates)
            )
        )
        version = self.session.exec(statement).first()

        if not version:
            raise HTTPException(
                404, "No technical versions found for this product.")

        # 3. Map to DTO
        return ProductVersionDetailRead(
            id=version.id,
            version_sequence=version.version_sequence,
            version_name=version.version_name,
            status=version.status,
            created_at=version.created_at,
            updated_at=version.updated_at,

            manufacturing_country=version.manufacturing_country,
            mass_kg=version.mass_kg,
            total_carbon_footprint=version.total_carbon_footprint,
            total_energy_mj=version.total_energy_mj,
            total_water_usage=version.total_water_usage,

            materials=[ProductMaterialRead(
                id=m.id,
                material_name=m.material_name,
                percentage=m.percentage,
                origin_country=m.origin_country,
                transport_method=m.transport_method
            ) for m in version.materials],

            supply_chain=[ProductSupplyNodeRead(
                id=s.id,
                role=s.role,
                company_name=s.company_name,
                location_country=s.location_country
            ) for s in version.supply_chain],

            certificates=[ProductCertificateRead(
                id=c.id,
                certificate_type_id=c.certificate_type_id,
                snapshot_name=c.snapshot_name,
                snapshot_issuer=c.snapshot_issuer,
                valid_until=c.valid_until,
                file_url=c.file_url,
                file_type=c.file_type
            ) for c in version.certificates]
        )

    # ==========================
    # COLLABORATION STATUS
    # ==========================

    def get_collaboration_status(self, user: User, product_id: uuid.UUID) -> ProductCollaborationStatusRead:
        """
        Returns the current workflow status of the product.
        Checks the active Request linked to the latest version.
        """
        brand = self._get_brand_tenant(user)

        # 1. Get Product & Latest Version
        product = self.session.get(Product, product_id)
        if not product or product.tenant_id != brand.id:
            raise HTTPException(404, "Product not found.")

        # Find latest version
        version = self.session.exec(
            select(ProductVersion)
            .where(ProductVersion.product_id == product_id)
            .order_by(ProductVersion.version_sequence.desc())
        ).first()

        if not version:
            # Shell created, but no version init (rare)
            return ProductCollaborationStatusRead(
                active_request_id=None,
                product_id=product.id,
                latest_version_id=None,
                request_status=None,
                version_status=ProductVersionStatus.DRAFT,
                last_updated_at=product.updated_at
            )

        # 2. Find THE Request defining the current state
        # We fetch the SINGLE most recent request.
        # Thanks to the Write Guard above, we know this is safe.
        request = self.session.exec(
            select(ProductContributionRequest)
            .where(ProductContributionRequest.current_version_id == version.id)
            .where(ProductContributionRequest.brand_tenant_id == brand.id)
            # Strictly get the latest event
            .order_by(ProductContributionRequest.created_at.desc())
        ).first()

        supplier_name = None
        supplier_country = None
        supplier_profile_id = None  # New

        if request:
            # 1. Get Name/Country from Real Tenant
            supplier = self.session.get(Tenant, request.supplier_tenant_id)
            if supplier:
                supplier_name = supplier.name
                supplier_country = supplier.location_country

            # 2. Get Profile ID from Connection
            # The Request has connection_id. The Connection has supplier_profile_id.
            connection = self.session.get(
                TenantConnection, request.connection_id)
            if connection:
                supplier_profile_id = connection.supplier_profile_id

        return ProductCollaborationStatusRead(
            active_request_id=request.id if request else None,

            product_id=product.id,
            latest_version_id=version.id,

            # Request Status (e.g., IN_PROGRESS, SUBMITTED)
            request_status=request.status if request else None,

            # Version Status (e.g., DRAFT, APPROVED)
            version_status=version.status,

            assigned_supplier_name=supplier_name,

            assigned_supplier_profile_id=supplier_profile_id,

            supplier_country=supplier_country,
            due_date=request.due_date if request else None,
            last_updated_at=request.updated_at if request else version.updated_at
        )

    def cancel_request(self, user: User, product_id: uuid.UUID, request_id: uuid.UUID, reason: str):
        brand = self._get_brand_tenant(user)

        request = self.session.get(ProductContributionRequest, request_id)
        if not request or request.brand_tenant_id != brand.id:
            raise HTTPException(404, "Request not found.")

        # Can only cancel if not completed/submitted/already cancelled
        if request.status in [RequestStatus.COMPLETED, RequestStatus.SUBMITTED, RequestStatus.CANCELLED]:
            raise HTTPException(
                400, "Cannot cancel request in current status.")

        request.status = RequestStatus.CANCELLED

        # Add cancellation note
        self.session.add(CollaborationComment(
            request_id=request.id,
            author_user_id=user.id,
            body=f"Request Cancelled: {reason}",
            is_rejection_reason=True
        ))

        self.session.add(request)
        self.session.commit()
        return {"message": "Request cancelled"}

    def review_submission(self, user: User, product_id: uuid.UUID, request_id: uuid.UUID, action: str, comment_text: str = None):
        brand = self._get_brand_tenant(user)

        # 1. Fetch Request
        request = self.session.get(ProductContributionRequest, request_id)
        if not request or request.brand_tenant_id != brand.id:
            raise HTTPException(404, "Request not found.")

        version = self.session.get(ProductVersion, request.current_version_id)

        # 2. Add Comment (if any)
        if comment_text:
            self.session.add(CollaborationComment(
                request_id=request.id,
                author_user_id=user.id,
                body=comment_text,
                is_rejection_reason=(action == 'request_changes')
            ))

        # 3. Handle Actions
        if action == 'approve':
            # Lock everything
            request.status = RequestStatus.COMPLETED
            version.status = ProductVersionStatus.APPROVED
            # Explicitly mark 'was_valid_at_submission' for certs if needed here

        elif action == 'request_changes':
            # Push back to supplier
            request.status = RequestStatus.CHANGES_REQUESTED
            # Unlock the version for editing (Revert to Draft)
            version.status = ProductVersionStatus.DRAFT

        else:
            raise HTTPException(
                400, "Invalid action. Use 'approve' or 'request_changes'.")

        self.session.add(request)
        self.session.add(version)
        self.session.commit()

        return {"message": f"Submission {action}d successfully."}
