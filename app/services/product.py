from typing import List, Optional
from uuid import UUID
from sqlmodel import Session, select
from fastapi import HTTPException
from loguru import logger

from app.models.product import (
    VersionMetadataUpdate, VersionImpactUpdate, ProductVersionSummary,
    MaterialAdd, SupplierAdd, CertificationAdd, ProductCreate, ProductRead, ProductDetailRead,
    MaterialUpdate, SupplierUpdate, CertificationUpdate, ProductImageAdd
)
from app.db.schema import (
    User, VersionMaterial, VersionSupplier, VersionCertification, ProductVersionMedia,
    Product, ProductVersion, VersionStatus, DataContributionRequest
)
from app.utils.file_storage import save_base64_image


class ProductService:
    def __init__(self, session: Session):
        self.session = session

    def _get_version_for_edit(self, user: User, version_id: UUID) -> ProductVersion:
        """Helper: Ensure user owns the product version via Tenant."""
        tenant_id = getattr(user, "_tenant_id")
        stmt = (
            select(ProductVersion)
            .join(Product)
            .where(ProductVersion.id == version_id)
            .where(Product.tenant_id == tenant_id)
        )
        version = self.session.exec(stmt).first()
        if not version:
            raise HTTPException(404, "Version not found or access denied.")
        if version.status in [VersionStatus.PUBLISHED, VersionStatus.ARCHIVED]:
            # Optional: Strict check to prevent editing published passports
            pass
        return version

    def create_product(self, user: User, data: ProductCreate) -> ProductRead:
        tenant_id = getattr(user, "_tenant_id")

        # 1. Check SKU Uniqueness (Tenant Scope)
        existing = self.session.exec(
            select(Product).where(Product.tenant_id ==
                                  tenant_id, Product.sku == data.sku)
        ).first()
        if existing:
            raise HTTPException(
                409, f"Product with SKU '{data.sku}' already exists.")

        try:
            # --- A. Create Immutable Product Shell ---
            product = Product(
                tenant_id=tenant_id,
                sku=data.sku,
                gtin=data.gtin
            )
            self.session.add(product)
            self.session.flush()  # Flush to get product.id

            # --- B. Create First Version (Draft) ---
            version = ProductVersion(
                product_id=product.id,
                created_by_tenant_id=tenant_id,

                # Version Metadata
                version_number=1,
                version_name=data.version_name,
                status=VersionStatus.WORKING_DRAFT,

                # Product Data (Mutable)
                product_name=data.name,
                category=data.product_type,
                description=data.description,

                # Init Environment Data as None/Empty
                manufacturing_country=None,
                total_carbon_footprint_kg=None
            )
            self.session.add(version)
            self.session.flush()  # Flush to get version.id

            # --- C. Handle Images (Save to Disk) ---
            main_image_url = None

            for idx, img in enumerate(data.images):
                # Ensure only one main image if frontend messed up, or take the first one
                is_main = img.is_main

                # 1. PROCESS IMAGE: Save Base64 to Disk and get URL
                try:
                    saved_file_url = save_base64_image(img.file_data)
                except Exception as e:
                    logger.error(f"Failed to save image {idx}: {e}")
                    continue  # Skip bad images but don't fail entire request

                # 2. SAVE DB RECORD
                media_entry = ProductVersionMedia(
                    version_id=version.id,
                    file_url=saved_file_url,  # Store the path, not the base64
                    is_main=is_main,
                    display_order=idx
                )
                self.session.add(media_entry)

                if is_main:
                    main_image_url = saved_file_url

            self.session.commit()
            self.session.refresh(product)

            # Map to Read Model
            # Fallback to first image URL if main was not explicitly set but images exist
            final_image_url = main_image_url
            if not final_image_url and data.images:
                # Re-query or infer from the logic above (simplification for response)
                # In a real scenario, we might query ProductVersionMedia back
                pass

            return ProductRead(
                id=product.id,
                tenant_id=product.tenant_id,
                sku=product.sku,
                gtin=product.gtin,
                name=version.product_name,
                category=version.category,
                latest_version_id=version.id,
                status=version.status,
                image_url=main_image_url  # This will now be http://.../static/products/xyz.png
            )

        except Exception as e:
            self.session.rollback()
            logger.error(f"Create Product Failed: {e}")
            raise HTTPException(500, "Failed to create product.")

    def list_products(self, user: User) -> List[ProductRead]:
        """
        List all products. 
        Fetches the 'Latest Version' to populate the mutable fields (Name, Image).
        """
        tenant_id = getattr(user, "_tenant_id")

        # 1. Fetch Products for this Tenant
        statement = select(Product).where(Product.tenant_id == tenant_id)
        products = self.session.exec(statement).all()

        results = []
        for product in products:
            # 2. Find Latest Version
            # In production, use a JOIN or Window Function.
            # For now, Python sorting is acceptable for smaller datasets.
            if not product.versions:
                continue

            latest_version = sorted(
                product.versions, key=lambda v: v.version_number, reverse=True)[0]

            # 3. Find Main Image
            main_img = next(
                (m for m in latest_version.media if m.is_main), None)
            # Fallback to first image if no main set
            if not main_img and latest_version.media:
                main_img = latest_version.media[0]

            results.append(ProductRead(
                id=product.id,
                tenant_id=product.tenant_id,
                sku=product.sku,
                gtin=product.gtin,

                # Mapped from Version
                name=latest_version.product_name,
                category=latest_version.category,
                latest_version_id=latest_version.id,
                status=latest_version.status,

                # Mapped from Media
                image_url=main_img.file_url if main_img else None
            ))

        return results

    def get_product_details(self, user: User, product_id: UUID, version_id: Optional[UUID] = None) -> ProductDetailRead:
        """
        Updated to support ?version_id=... selection
        """
        tenant_id = getattr(user, "_tenant_id")

        # 1. Fetch Product
        product = self.session.exec(
            select(Product).where(Product.id == product_id,
                                  Product.tenant_id == tenant_id)
        ).first()

        if not product:
            raise HTTPException(404, "Product not found")

        # 2. Determine Target Version
        target_version = None

        # Sort history for the dropdown list
        history_list = sorted(
            product.versions, key=lambda v: v.version_number, reverse=True
        )

        if version_id:
            # Specific version requested (Switching versions)
            target_version = next(
                (v for v in history_list if v.id == version_id), None)
            if not target_version:
                raise HTTPException(404, "Requested version not found.")
        else:
            # Default to latest
            if not history_list:
                raise HTTPException(500, "Product has no versions.")
            target_version = history_list[0]

        # 3. Get Main Image
        media_list = target_version.media
        main_img = next((m for m in media_list if m.is_main), None)
        if not main_img and media_list:
            main_img = media_list[0]

        # 4. Build Response
        return ProductDetailRead(
            id=product.id,
            sku=product.sku,
            gtin=product.gtin,

            active_version_id=target_version.id,
            name=target_version.product_name,
            category=target_version.category,
            description=target_version.description,
            image_url=main_img.file_url if main_img else None,

            # Relationships for THIS specific version
            images=media_list,
            materials=target_version.materials,
            supply_chain=target_version.suppliers,
            certifications=target_version.certifications,
            impact={
                "carbon": target_version.total_carbon_footprint_kg,
                "water": target_version.total_water_usage_liters,
                "energy": target_version.total_energy_mj,
                "country": target_version.manufacturing_country
            },

            versions=[
                ProductVersionSummary(
                    id=v.id,
                    version_name=v.version_name,
                    version_number=v.version_number,
                    status=v.status,
                    created_at=v.created_at
                ) for v in history_list
            ]
        )

    # --- 1. OVERVIEW & METADATA ---

    def update_version_metadata(self, user: User, version_id: UUID, data: VersionMetadataUpdate):
        version = self._get_version_for_edit(user, version_id)

        # Update Mutable Version Data
        if data.product_name is not None:
            version.product_name = data.product_name
        if data.category is not None:
            version.category = data.category
        if data.description is not None:
            version.description = data.description
        if data.version_name is not None:
            version.version_name = data.version_name

        # Update Parent Product Data (GTIN) if provided
        if data.gtin is not None:
            product = self.session.get(Product, version.product_id)
            if product:
                product.gtin = data.gtin
                self.session.add(product)

        self.session.add(version)
        self.session.commit()
        return {"message": "Product overview updated"}

    # --- 2. IMPACT ---

    def update_version_impact(self, user: User, version_id: UUID, data: VersionImpactUpdate):
        version = self._get_version_for_edit(user, version_id)
        for key, val in data.model_dump(exclude_unset=True).items():
            setattr(version, key, val)
        self.session.add(version)
        self.session.commit()
        return {"message": "Impact data updated"}

    # --- 3. MATERIALS (Add, Update, Delete) ---

    def add_material(self, user: User, version_id: UUID, data: MaterialAdd):
        version = self._get_version_for_edit(user, version_id)
        is_unlisted = data.material_id is None
        item = VersionMaterial(
            version_id=version.id,
            material_id=data.material_id,
            unlisted_material_name=data.name if is_unlisted else None,
            percentage=data.percentage,
            origin_country=data.origin_country,
            transport_method=data.transport_method
        )
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def update_material(self, user: User, version_id: UUID, item_id: UUID, data: MaterialUpdate):
        """Update a specific material line item."""
        self._get_version_for_edit(user, version_id)  # Auth check
        item = self.session.get(VersionMaterial, item_id)
        if not item or item.version_id != version_id:
            raise HTTPException(404, "Material item not found.")

        if data.material_id is not None:
            item.material_id = data.material_id
        if data.name is not None:
            item.unlisted_material_name = data.name
        if data.percentage is not None:
            item.percentage = data.percentage
        if data.origin_country is not None:
            item.origin_country = data.origin_country
        if data.transport_method is not None:
            item.transport_method = data.transport_method

        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def remove_material(self, user: User, version_id: UUID, item_id: UUID):
        self._get_version_for_edit(user, version_id)  # Auth check
        item = self.session.get(VersionMaterial, item_id)
        if item and item.version_id == version_id:
            self.session.delete(item)
            self.session.commit()

    # --- 4. SUPPLY CHAIN (Add, Update, Delete) ---

    def add_supplier(self, user: User, version_id: UUID, data: SupplierAdd):
        version = self._get_version_for_edit(user, version_id)
        is_unlisted = data.supplier_profile_id is None
        item = VersionSupplier(
            version_id=version.id,
            supplier_profile_id=data.supplier_profile_id,
            unlisted_supplier_name=data.name if is_unlisted else None,
            unlisted_supplier_country=data.country if is_unlisted else None,
            role=data.role
        )
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def update_supplier(self, user: User, version_id: UUID, item_id: UUID, data: SupplierUpdate):
        self._get_version_for_edit(user, version_id)
        item = self.session.get(VersionSupplier, item_id)
        if not item or item.version_id != version_id:
            raise HTTPException(404, "Supplier node not found.")

        if data.supplier_profile_id is not None:
            item.supplier_profile_id = data.supplier_profile_id
        if data.name is not None:
            item.unlisted_supplier_name = data.name
        if data.country is not None:
            item.unlisted_supplier_country = data.country
        if data.role is not None:
            item.role = data.role

        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def remove_supplier(self, user: User, version_id: UUID, item_id: UUID):
        self._get_version_for_edit(user, version_id)
        item = self.session.get(VersionSupplier, item_id)
        if item and item.version_id == version_id:
            self.session.delete(item)
            self.session.commit()

    # --- 5. CERTIFICATIONS (Add, Update, Delete) ---

    def add_certification(self, user: User, version_id: UUID, data: CertificationAdd):
        version = self._get_version_for_edit(user, version_id)
        item = VersionCertification(
            version_id=version.id,
            certification_id=data.certification_id,
            document_url=data.document_url,
            valid_until=data.valid_until
        )
        self.session.add(item)
        self.session.commit()
        return item

    def update_certification(self, user: User, version_id: UUID, item_id: UUID, data: CertificationUpdate):
        self._get_version_for_edit(user, version_id)
        item = self.session.get(VersionCertification, item_id)
        if not item or item.version_id != version_id:
            raise HTTPException(404, "Certification not found.")

        if data.certification_id is not None:
            item.certification_id = data.certification_id
        if data.document_url is not None:
            item.document_url = data.document_url
        if data.valid_until is not None:
            item.valid_until = data.valid_until

        self.session.add(item)
        self.session.commit()
        return item

    def remove_certification(self, user: User, version_id: UUID, item_id: UUID):
        self._get_version_for_edit(user, version_id)
        item = self.session.get(VersionCertification, item_id)
        if item and item.version_id == version_id:
            self.session.delete(item)
            self.session.commit()

    # --- 6. MEDIA (Add, Delete, Set Main) ---

    def add_image(self, user: User, version_id: UUID, data: ProductImageAdd):
        version = self._get_version_for_edit(user, version_id)

        # 1. Save Base64 to disk
        file_url = save_base64_image(data.file_data)

        # 2. Check if we need to unset existing main
        if data.is_main:
            existing_main = self.session.exec(select(ProductVersionMedia).where(
                ProductVersionMedia.version_id == version_id, ProductVersionMedia.is_main == True)).first()
            if existing_main:
                existing_main.is_main = False
                self.session.add(existing_main)

        # 3. Add new
        media = ProductVersionMedia(
            version_id=version_id,
            file_url=file_url,
            is_main=data.is_main,
            display_order=99  # Append to end
        )
        self.session.add(media)
        self.session.commit()
        return media

    def delete_image(self, user: User, version_id: UUID, media_id: UUID):
        self._get_version_for_edit(user, version_id)
        media = self.session.get(ProductVersionMedia, media_id)
        if media and media.version_id == version_id:
            self.session.delete(media)
            self.session.commit()
        else:
            raise HTTPException(404, "Image not found")

    def set_main_image(self, user: User, version_id: UUID, media_id: UUID):
        self._get_version_for_edit(user, version_id)

        # Unset current main
        current_main = self.session.exec(select(ProductVersionMedia).where(
            ProductVersionMedia.version_id == version_id, ProductVersionMedia.is_main == True)).all()
        for img in current_main:
            img.is_main = False
            self.session.add(img)

        # Set new main
        new_main = self.session.get(ProductVersionMedia, media_id)
        if new_main and new_main.version_id == version_id:
            new_main.is_main = True
            self.session.add(new_main)
            self.session.commit()
        else:
            raise HTTPException(404, "Image not found")
