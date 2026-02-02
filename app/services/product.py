import uuid
from typing import List, Optional
from datetime import datetime, timezone
from loguru import logger
from sqlmodel import Session, select, col
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, BackgroundTasks

from app.db.schema import (
    User, Tenant, TenantType,
    Product, ProductMedia,
    AuditAction, SupplierProfile,
    ProductVersion, ProductVersionStatus
)
from app.models.product import (
    ProductCreate, ProductIdentityUpdate, ProductRead,
    ProductMediaAdd, ProductMediaRead, ProductMediaReorder,
    ProductReadDetailView, ProductVersionSummary, ProductVersionGroup,
)
from app.utils.file_storage import save_base64_image
from app.core.audit import _perform_audit_log


class ProductService:
    def __init__(self, session: Session):
        self.session = session

    # ==========================================================================
    # HELPERS
    # ==========================================================================

    def _get_brand_context(self, user: User) -> Tenant:
        """
        Helper: Strictly enforces that the tenant is a BRAND.
        Only Brands can define Product Identity (The Shell).
        """
        tenant_id = getattr(user, "_tenant_id", None)
        if not tenant_id:
            raise HTTPException(
                status_code=403, detail="No active tenant context.")

        tenant = self.session.get(Tenant, tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        if tenant.type != TenantType.BRAND:
            raise HTTPException(
                status_code=403,
                detail="Access Forbidden. Only Brand Tenants can manage Product Identity."
            )
        return tenant

    def _check_sku_uniqueness(self, tenant_id: uuid.UUID, sku: str, exclude_id: Optional[uuid.UUID] = None):
        """
        Enforces uniqueness for SKU within the Tenant.
        """
        statement = select(Product).where(
            Product.tenant_id == tenant_id,
            Product.sku == sku
        )

        if exclude_id:
            statement = statement.where(Product.id != exclude_id)

        existing = self.session.exec(statement).first()

        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Conflict detected: The SKU '{sku}' already exists in your library."
            )

    def _map_to_read_model(self, product: Product) -> ProductRead:
        """
        Internal Helper: Maps a DB Product entity to the Read model.

        CRITICAL: Filters out Soft-Deleted Media.
        """
        # 1. Determine Active Version Name
        latest_v_id = None
        latest_v_name = product.pending_version_name

        if product.technical_versions:
            # Sort descending by sequence
            latest_v = sorted(
                product.technical_versions,
                key=lambda v: v.version_sequence,
                reverse=True
            )[0]
            latest_v_id = latest_v.id
            latest_v_name = latest_v.version_name

        # 2. Filter and Sort Media
        # Soft Delete Check: We must exclude is_deleted=True
        active_media = [
            m for m in product.marketing_media
            if not m.is_deleted
        ]

        sorted_media = sorted(
            active_media, key=lambda m: m.display_order
        )

        media_dtos = [
            ProductMediaRead(
                id=m.id,
                file_url=m.file_url,
                file_name=m.file_name,
                file_type=m.file_type,
                display_order=m.display_order,
                is_main=m.is_main,
                description=m.description
            )
            for m in sorted_media
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
            latest_version_id=latest_v_id,
            latest_version_name=latest_v_name,
            media=media_dtos,
            created_at=product.created_at,
            updated_at=product.updated_at
        )

    def _unset_main_media_internal(self, product_id: uuid.UUID):
        """
        Private Helper: Sets is_main=False for all active media of a product.
        """
        # We only care about active media, though checking all doesn't hurt.
        existing = self.session.exec(
            select(ProductMedia)
            .where(ProductMedia.product_id == product_id)
            .where(ProductMedia.is_main == True)
            .where(ProductMedia.is_deleted == False)
        ).all()
        for img in existing:
            img.is_main = False
            self.session.add(img)

    # ==========================================================================
    # READ OPERATIONS
    # ==========================================================================

    def list_products(self, user: User, query: Optional[str] = None) -> List[ProductRead]:
        """
        List all products for the Brand.
        """
        brand = self._get_brand_context(user)

        statement = (
            select(Product)
            .where(Product.tenant_id == brand.id)
            .options(selectinload(Product.technical_versions))
            .options(selectinload(Product.marketing_media))
            .order_by(Product.created_at.desc())
        )

        if query:
            search_fmt = f"%{query}%"
            statement = statement.where(
                col(Product.name).ilike(search_fmt) |
                col(Product.sku).ilike(search_fmt)
            )

        products = self.session.exec(statement).all()

        return [self._map_to_read_model(p) for p in products]

    def get_product(self, user: User, product_id: uuid.UUID) -> ProductReadDetailView:
        """
        Get single product details with full media gallery.
        """
        brand = self._get_brand_context(user)

        product = self.session.exec(
            select(Product)
            .where(Product.id == product_id, Product.tenant_id == brand.id)
            .options(selectinload(Product.technical_versions))
            .options(selectinload(Product.marketing_media))
        ).first()

        if not product:
            raise HTTPException(status_code=404, detail="Product not found.")

        # 1. Base Mapping
        base_read = self._map_to_read_model(product)

        # 2. Lift to Detail View
        detail_view = ProductReadDetailView.model_validate(
            base_read.model_dump()
        )

        # 3. Populate Versions (History)
        if product.technical_versions:
            # Sort by sequence desc
            sorted_versions = sorted(
                product.technical_versions,
                key=lambda v: v.version_sequence,
                reverse=True
            )

            # Collect all unique supplier tenant IDs from the versions
            supplier_tenant_ids = {
                v.supplier_tenant_id for v in sorted_versions if v.supplier_tenant_id
            }

            # Fetch Supplier Profiles for these tenants (Scoped to Brand's Address Book)
            supplier_map = {}
            if supplier_tenant_ids:
                profiles = self.session.exec(
                    select(SupplierProfile)
                    .where(
                        SupplierProfile.tenant_id == brand.id,
                        col(SupplierProfile.supplier_tenant_id).in_(
                            supplier_tenant_ids)
                    )
                ).all()
                # Create map: supplier_tenant_id -> SupplierProfile
                for prof in profiles:
                    if prof.supplier_tenant_id:
                        supplier_map[prof.supplier_tenant_id] = prof

            detail_view.versions = []
            for v in sorted_versions:
                summary = ProductVersionSummary(
                    id=v.id,
                    version_sequence=v.version_sequence,
                    revision=v.revision,
                    version_name=v.version_name,
                    status=v.status,
                    created_at=v.created_at,
                    updated_at=v.updated_at,
                    is_latest=False
                )

                # Attach Supplier Info
                if v.supplier_tenant_id and v.supplier_tenant_id in supplier_map:
                    profile = supplier_map[v.supplier_tenant_id]
                    summary.supplier_name = profile.name
                    # The ID of the SupplierProfile (Address Book Entry)
                    summary.supplier_id = profile.id

                detail_view.versions.append(summary)

        return detail_view

    # ==========================================================================
    # CREATE OPERATION
    # ==========================================================================

    def create_product(
        self,
        user: User,
        data: ProductCreate,
        background_tasks: BackgroundTasks
    ) -> ProductRead:
        """
        Creates Product Identity + Initial Media.
        """
        brand = self._get_brand_context(user)

        # 1. Uniqueness Check
        self._check_sku_uniqueness(brand.id, data.sku)

        try:
            # 2. Create Shell
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
            self.session.flush()

            # 3. Handle Media
            main_url = None
            media_audit_list = []

            if data.media_files:
                for idx, media_item in enumerate(data.media_files):
                    file_url = save_base64_image(media_item.file_data)

                    media_entry = ProductMedia(
                        product_id=product.id,
                        file_url=file_url,
                        file_name=media_item.file_name,
                        file_type=media_item.file_type,
                        description=media_item.description,
                        is_main=media_item.is_main,
                        display_order=idx,
                        is_deleted=False  # Explicitly set for clarity
                    )
                    self.session.add(media_entry)

                    if media_item.is_main:
                        main_url = file_url

                    media_audit_list.append(media_item.file_name)

            # 4. Update Cache
            if main_url:
                product.main_image_url = main_url
                self.session.add(product)

            self.session.commit()
            self.session.refresh(product)

            # Re-fetch for clean read model
            product = self.session.exec(
                select(Product)
                .where(Product.id == product.id)
                .options(selectinload(Product.marketing_media))
            ).first()

            # 5. Audit
            audit_changes = data.model_dump(exclude={"media_files"})
            audit_changes["added_media_files"] = media_audit_list

            background_tasks.add_task(
                _perform_audit_log,
                tenant_id=brand.id,
                user_id=user.id,
                entity_type="Product",
                entity_id=product.id,
                action=AuditAction.CREATE,
                changes=audit_changes
            )

            return self._map_to_read_model(product)

        except Exception as e:
            self.session.rollback()
            logger.error(f"Product creation failed: {e}")
            raise HTTPException(
                status_code=500, detail="Could not create product.")

    def get_version_history(self, user: User, product_id: uuid.UUID) -> List[ProductVersionGroup]:
        """
        Returns all versions grouped by sequence with their revisions.
        Used by frontend to build hierarchical version tree and comparison picker.
        """
        brand = self._get_brand_context(user)

        product = self.session.get(Product, product_id)
        if not product or product.tenant_id != brand.id:
            raise HTTPException(status_code=404, detail="Product not found.")

        # Fetch all versions for this product
        versions = self.session.exec(
            select(ProductVersion)
            .where(ProductVersion.product_id == product_id)
            .order_by(
                ProductVersion.version_sequence.desc(),
                ProductVersion.revision.desc()
            )
        ).all()

        if not versions:
            return []

        # Find absolute latest version
        latest_version_id = versions[0].id if versions else None

        # Group by version_sequence
        from collections import defaultdict
        groups_dict = defaultdict(list)

        for v in versions:
            groups_dict[v.version_sequence].append(v)

        # Build response groups
        result = []
        for seq in sorted(groups_dict.keys(), reverse=True):
            revisions_list = groups_dict[seq]
            latest_rev = revisions_list[0]  # Already sorted DESC

            # Resolve supplier info (if any)
            # We look for the latest request linked to any revision in this sequence
            supplier_name = None
            supplier_id = None

            # Simple approach: check latest revision for supplier info
            # In real system, you might query ProductContributionRequest
            # For now, leave as None (can be enhanced later)

            revision_summaries = [
                ProductVersionSummary(
                    id=rev.id,
                    version_sequence=rev.version_sequence,
                    revision=rev.revision,
                    version_name=rev.version_name,
                    status=rev.status,
                    created_at=rev.created_at,
                    updated_at=rev.updated_at,
                    supplier_name=supplier_name,
                    supplier_id=supplier_id,
                    is_latest=(rev.id == latest_version_id)
                )
                for rev in revisions_list
            ]

            result.append(ProductVersionGroup(
                version_sequence=seq,
                version_name=latest_rev.version_name,
                latest_status=latest_rev.status,
                latest_revision=latest_rev.revision,
                revisions=revision_summaries
            ))

        return result

    # ==========================================================================
    # UPDATE IDENTITY
    # ==========================================================================

    def update_product_identity(
        self,
        user: User,
        product_id: uuid.UUID,
        data: ProductIdentityUpdate,
        background_tasks: BackgroundTasks
    ) -> ProductRead:
        brand = self._get_brand_context(user)

        product = self.session.get(Product, product_id)
        if not product or product.tenant_id != brand.id:
            raise HTTPException(status_code=404, detail="Product not found.")

        old_state = product.model_dump()

        if data.name is not None:
            product.name = data.name
        if data.description is not None:
            product.description = data.description
        if data.ean is not None:
            product.ean = data.ean
        if data.upc is not None:
            product.upc = data.upc
        if data.lifecycle_status is not None:
            product.lifecycle_status = data.lifecycle_status

        self.session.add(product)
        self.session.commit()
        self.session.refresh(product)

        # Audit
        new_state = data.model_dump(exclude_unset=True)
        changes = {k: {"old": old_state.get(k), "new": v}
                   for k, v in new_state.items()}

        background_tasks.add_task(
            _perform_audit_log,
            tenant_id=brand.id,
            user_id=user.id,
            entity_type="Product",
            entity_id=product.id,
            action=AuditAction.UPDATE,
            changes=changes
        )

        return self.get_product(user, product_id)

    # ==========================================================================
    # MEDIA MANAGEMENT
    # ==========================================================================

    def add_media(
        self,
        user: User,
        product_id: uuid.UUID,
        data: ProductMediaAdd,
        background_tasks: BackgroundTasks
    ) -> ProductMediaRead:
        brand = self._get_brand_context(user)

        product = self.session.get(Product, product_id)
        if not product or product.tenant_id != brand.id:
            raise HTTPException(status_code=404, detail="Product not found.")

        # If setting as main, unset others first
        if data.is_main:
            self._unset_main_media_internal(product.id)

        file_url = save_base64_image(data.file_data)

        # Calculate Order: Count only ACTIVE media
        active_count = self.session.exec(
            select(ProductMedia)
            .where(ProductMedia.product_id == product.id)
            .where(ProductMedia.is_deleted == False)
        ).all()
        next_order = len(active_count)

        media = ProductMedia(
            product_id=product.id,
            file_url=file_url,
            file_name=data.file_name,
            file_type=data.file_type,
            description=data.description,
            is_main=data.is_main,
            display_order=next_order,
            is_deleted=False
        )
        self.session.add(media)

        if data.is_main:
            product.main_image_url = file_url
            self.session.add(product)

        self.session.commit()
        self.session.refresh(media)

        background_tasks.add_task(
            _perform_audit_log,
            tenant_id=brand.id,
            user_id=user.id,
            entity_type="ProductMedia",
            entity_id=media.id,
            action=AuditAction.CREATE,
            changes={"file_name": data.file_name, "is_main": data.is_main}
        )

        return ProductMediaRead(
            id=media.id,
            file_url=media.file_url,
            file_name=media.file_name,
            file_type=media.file_type,
            display_order=media.display_order,
            is_main=media.is_main,
            description=media.description
        )

    def delete_media(
        self,
        user: User,
        media_id: uuid.UUID,
        background_tasks: BackgroundTasks
    ):
        """
        PERFORMS SOFT DELETE.
        Flags the record as deleted and unlinks from Main Image Cache if necessary.
        """
        brand = self._get_brand_context(user)

        media = self.session.get(ProductMedia, media_id)
        if not media or media.is_deleted:
            raise HTTPException(status_code=404, detail="Media not found.")

        product = self.session.get(Product, media.product_id)
        if product.tenant_id != brand.id:
            raise HTTPException(status_code=403, detail="Access denied.")

        was_main = media.is_main

        # Soft Delete
        media.is_deleted = True
        media.deleted_at = datetime.now(timezone.utc)
        media.is_main = False  # Cannot be main if deleted
        self.session.add(media)

        # Update Product Cache if we deleted the main image
        if was_main:
            product.main_image_url = None
            self.session.add(product)

        self.session.commit()

        # Audit
        background_tasks.add_task(
            _perform_audit_log,
            tenant_id=brand.id,
            user_id=user.id,
            entity_type="ProductMedia",
            entity_id=media_id,
            action=AuditAction.DELETE,
            changes={
                "file_name": media.file_name,
                "was_main": was_main,
                "deleted_at": str(media.deleted_at)
            }
        )
        return {"message": "Media deleted successfully."}

    def set_main_media(
        self,
        user: User,
        product_id: uuid.UUID,
        media_id: uuid.UUID,
        background_tasks: BackgroundTasks
    ):
        brand = self._get_brand_context(user)

        product = self.session.get(Product, product_id)
        if not product or product.tenant_id != brand.id:
            raise HTTPException(status_code=404, detail="Product not found.")

        media = self.session.get(ProductMedia, media_id)
        if not media or media.is_deleted:
            raise HTTPException(status_code=404, detail="Media not found.")

        if media.product_id != product_id:
            raise HTTPException(
                status_code=400, detail="Media does not belong to this product.")

        self._unset_main_media_internal(product_id)

        media.is_main = True
        self.session.add(media)

        product.main_image_url = media.file_url
        self.session.add(product)

        self.session.commit()

        background_tasks.add_task(
            _perform_audit_log,
            tenant_id=brand.id,
            user_id=user.id,
            entity_type="Product",
            entity_id=product_id,
            action=AuditAction.UPDATE,
            changes={"action": "set_main_image",
                     "new_main_media_id": str(media_id)}
        )

        return {"message": "Main image updated successfully."}

    def reorder_media(
        self,
        user: User,
        product_id: uuid.UUID,
        order_list: List[ProductMediaReorder],
        background_tasks: BackgroundTasks
    ):
        brand = self._get_brand_context(user)

        product = self.session.get(Product, product_id)
        if not product or product.tenant_id != brand.id:
            raise HTTPException(status_code=403, detail="Access denied.")

        for item in order_list:
            media = self.session.get(ProductMedia, item.media_id)
            # Ensure media is valid, belongs to product, and IS NOT DELETED
            if media and media.product_id == product_id and not media.is_deleted:
                media.display_order = item.new_order
                self.session.add(media)

        self.session.commit()

        background_tasks.add_task(
            _perform_audit_log,
            tenant_id=brand.id,
            user_id=user.id,
            entity_type="Product",
            entity_id=product_id,
            action=AuditAction.UPDATE,
            changes={"action": "reorder_media",
                     "items_reordered": len(order_list)}
        )

        return {"message": "Media reordered successfully."}
