import uuid
from typing import List
from loguru import logger
from sqlmodel import Session, select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, BackgroundTasks

from app.db.schema import (
    User, Tenant, TenantType,
    Product, ProductMedia, ProductVersion, ProductVersionStatus,
    AuditAction, ProductContributionRequest, CollaborationComment, ConnectionStatus, SupplierProfile, RequestStatus
)
from app.models.product import (
    ProductCreate, ProductIdentityUpdate, ProductRead,
    ProductMediaAdd, ProductMediaRead, ProductMediaReorder, ProductAssignmentRequest
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

        Logic:
        1. Validates Brand owns Product.
        2. Validates Supplier Profile belongs to Brand and is Connected.
        3. VERSION LOGIC:
           - If no versions exist: Creates v1 (Draft) using 'pending_version_name'.
           - If latest is Locked (Submitted/Approved): Clones it to new v(N+1) Draft.
           - If latest is Draft: Re-assigns ownership to new Supplier.
        4. Creates 'ProductContributionRequest'.
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

        # Check the B2B Handshake
        # We access the relationship 'connection' on SupplierProfile (1:1)
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
            # SCENARIO A: First Assignment (Initialize v1)
            # Use the name the brand set during shell creation, or fallback
            v_name = product.pending_version_name or "Initial Version"

            target_version = ProductVersion(
                product_id=product.id,
                supplier_tenant_id=real_supplier_id,
                version_sequence=1,
                version_name=v_name,
                status=ProductVersionStatus.DRAFT
            )
            self.session.add(target_version)

            # Clear the pending name from shell as it is now realized
            product.pending_version_name = None
            self.session.add(product)
            self.session.flush()

        else:
            latest = existing_versions[0]

            if latest.status in [ProductVersionStatus.APPROVED, ProductVersionStatus.SUBMITTED]:
                # SCENARIO B: Previous version locked -> Clone new Draft
                # (Assuming _clone_version_structure helper exists in this class or util)
                target_version = self._clone_version_helper(latest)
                target_version.supplier_tenant_id = real_supplier_id
                target_version.version_sequence = latest.version_sequence + 1
                target_version.status = ProductVersionStatus.DRAFT
                self.session.add(target_version)
                self.session.flush()
            else:
                # SCENARIO C: Re-assigning an existing Draft
                latest.supplier_tenant_id = real_supplier_id
                target_version = latest
                self.session.add(target_version)

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
            # Note: Deep copy of materials/certs usually handled by explicit loop
            # in the main logic if needed, or initialized empty for new draft
        )
