from uuid import UUID
from typing import List
from fastapi import HTTPException, status
from sqlmodel import Session, select
from sqlalchemy.orm import selectinload

from app.db.schema import (
    User, Product, ProductDurability, ProductEnvironmental, SparePart,
    Material, Supplier, ProductMaterialLink, ProductSupplierLink, ProductCertificationLink
)
from app.models.product import ProductCreate, ProductUpdate, ProductFullDetailsRead
from app.models.product_durability import ProductDurabilityUpdate
from app.models.product_environmental import ProductEnvironmentalUpdate
from app.models.product_material import ProductMaterialLinkCreate, ProductMaterialLinkRead
from app.models.product_supplier import ProductSupplierLinkCreate, ProductSupplierLinkRead
from app.models.product_certification import ProductCertificationLinkCreate, ProductCertificationLinkRead
from app.models.product_spare_part import SparePartCreate, SparePartRead


class ProductService:
    def __init__(self, session: Session):
        self.session = session

    def get_product_by_id(self, user: User, product_id: UUID) -> Product:
        product = self.session.exec(
            select(Product).where(
                Product.id == product_id,
                Product.tenant_id == user._tenant_id
            )
        ).first()

        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found."
            )
        return product

    def list_products(self, user: User) -> List[Product]:
        query = (
            select(Product)
            .where(Product.tenant_id == user._tenant_id)
            .order_by(Product.created_at.desc())
        )
        return self.session.exec(query).all()

    def create_product(self, user: User, data: ProductCreate) -> Product:
        if data.gtin:
            existing = self.session.exec(
                select(Product).where(Product.gtin == data.gtin,
                                      Product.tenant_id == user._tenant_id)
            ).first()
            if existing:
                raise HTTPException(
                    status_code=409, detail=f"Product with GTIN {data.gtin} already exists.")

        product = Product(**data.model_dump(), tenant_id=user._tenant_id)
        self.session.add(product)
        self.session.commit()
        self.session.refresh(product)
        return product

    def update_product(self, user: User, product_id: UUID, data: ProductUpdate) -> Product:
        product = self.get_product_by_id(user, product_id)

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(product, key, value)

        self.session.add(product)
        self.session.commit()
        self.session.refresh(product)
        return product

    def get_product_full(self, user: User, product_id: UUID) -> ProductFullDetailsRead:
        """
        Fetches the complete Digital Product Passport.
        """
        query = (
            select(Product)
            .where(Product.id == product_id, Product.tenant_id == user._tenant_id)
            .options(
                selectinload(Product.durability),
                selectinload(Product.environmental),
                selectinload(Product.spare_parts),
                selectinload(Product.materials).selectinload(
                    ProductMaterialLink.material),
                selectinload(Product.suppliers).selectinload(
                    ProductSupplierLink.supplier),
                selectinload(Product.certifications).selectinload(
                    ProductCertificationLink.certification)
            )
        )

        product = self.session.exec(query).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        # TRANSFORM: Map DB Models to API Read Models

        # 1. Materials
        material_dtos = [
            ProductMaterialLinkRead(
                **link.model_dump(),
                material_name=link.material.name,
                material_code=link.material.code
            ) for link in product.materials
        ]

        # 2. Suppliers
        supplier_dtos = [
            ProductSupplierLinkRead(
                **link.model_dump(),
                supplier_name=link.supplier.name,
                supplier_country=link.supplier.location_country
            ) for link in product.suppliers
        ]

        # 3. Certifications
        cert_dtos = [
            ProductCertificationLinkRead(
                **link.model_dump(),
                certification_name=link.certification.name,
                issuer=link.certification.issuer
            ) for link in product.certifications
        ]

        # FIX: Remove explicit 'created_at' and 'updated_at' args.
        # **product.model_dump() already includes them.
        return ProductFullDetailsRead(
            **product.model_dump(),
            durability=product.durability,
            environmental=product.environmental,
            materials=material_dtos,
            suppliers=supplier_dtos,
            certifications=cert_dtos,
            spare_parts=[SparePartRead.model_validate(
                p) for p in product.spare_parts]
        )

    def upsert_durability(self, user: User, product_id: UUID, data: ProductDurabilityUpdate) -> ProductDurability:
        self.get_product_by_id(user, product_id)
        durability_record = self.session.exec(
            select(ProductDurability).where(
                ProductDurability.product_id == product_id)
        ).first()

        if durability_record:
            for key, value in data.model_dump(exclude_unset=True).items():
                setattr(durability_record, key, value)
        else:
            durability_record = ProductDurability(
                product_id=product_id,
                **data.model_dump()
            )

        self.session.add(durability_record)
        self.session.commit()
        self.session.refresh(durability_record)
        return durability_record

    def upsert_environmental(self, user: User, product_id: UUID, data: ProductEnvironmentalUpdate) -> ProductEnvironmental:
        self.get_product_by_id(user, product_id)
        env_record = self.session.exec(
            select(ProductEnvironmental).where(
                ProductEnvironmental.product_id == product_id)
        ).first()

        if env_record:
            for key, value in data.model_dump(exclude_unset=True).items():
                setattr(env_record, key, value)
        else:
            env_record = ProductEnvironmental(
                product_id=product_id,
                **data.model_dump()
            )

        self.session.add(env_record)
        self.session.commit()
        self.session.refresh(env_record)
        return env_record

    def add_material_link(self, user: User, product_id: UUID, data: ProductMaterialLinkCreate):
        """
        Idempotent (Upsert): 
        If material is already linked, UPDATE the percentage/origin. 
        If not, CREATE the link.
        """
        product = self.get_product_by_id(user, product_id)
        tenant_id = product.tenant_id

        # Validate Material
        material = self.session.exec(select(Material).where(
            Material.id == data.material_id)).first()
        if not material:
            raise HTTPException(status_code=404, detail="Material not found")

        if material.tenant_id and material.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403, detail="Cannot access this material")

        # Check existence
        existing_link = self.session.exec(
            select(ProductMaterialLink).where(
                ProductMaterialLink.product_id == product_id,
                ProductMaterialLink.material_id == data.material_id
            )
        ).first()

        if existing_link:
            # UPDATE existing link
            existing_link.percentage = data.percentage
            existing_link.is_recycled = data.is_recycled
            existing_link.origin_country = data.origin_country
            self.session.add(existing_link)
        else:
            # CREATE new link
            new_link = ProductMaterialLink(
                product_id=product_id, **data.model_dump())
            self.session.add(new_link)

        self.session.commit()
        return {"status": "synced", "material_id": data.material_id}

    def add_supplier_link(self, user: User, product_id: UUID, data: ProductSupplierLinkCreate):
        """
        Idempotent:
        If (Product + Supplier + Role) exists -> Return Success (Do nothing).
        If not -> Create Link.
        """
        product = self.get_product_by_id(user, product_id)

        # 1. Verify Supplier
        supplier = self.session.exec(
            select(Supplier).where(
                Supplier.id == data.supplier_id,
                Supplier.tenant_id == product.tenant_id
            )
        ).first()

        if not supplier:
            raise HTTPException(
                status_code=404, detail="Supplier not found or access denied")

        # 2. Check for EXACT duplicate
        existing_link = self.session.exec(
            select(ProductSupplierLink).where(
                ProductSupplierLink.product_id == product_id,
                ProductSupplierLink.supplier_id == data.supplier_id,
                ProductSupplierLink.role == data.role
            )
        ).first()

        if existing_link:
            # Already exists, return success to frontend
            return {
                "status": "exists",
                "supplier_id": data.supplier_id,
                "role": data.role
            }

        # 3. Create Link
        link = ProductSupplierLink(product_id=product_id, **data.model_dump())
        self.session.add(link)
        self.session.commit()

        return {
            "status": "created",
            "supplier_id": data.supplier_id,
            "role": data.role
        }

    def add_certification_link(self, user: User, product_id: UUID, data: ProductCertificationLinkCreate):
        """
        Idempotent (Upsert):
        If Certification is linked, UPDATE validity/url.
        If not, CREATE link.
        """
        self.get_product_by_id(user, product_id)

        # Check existence
        existing_link = self.session.exec(
            select(ProductCertificationLink).where(
                ProductCertificationLink.product_id == product_id,
                ProductCertificationLink.certification_id == data.certification_id
            )
        ).first()

        if existing_link:
            # Update
            existing_link.certificate_number = data.certificate_number
            existing_link.valid_until = data.valid_until
            existing_link.digital_document_url = data.digital_document_url
            self.session.add(existing_link)
        else:
            # Create
            link = ProductCertificationLink(
                product_id=product_id, **data.model_dump())
            self.session.add(link)

        self.session.commit()
        return {"status": "synced", "certification_id": data.certification_id}

    def add_spare_part(self, user: User, product_id: UUID, data: SparePartCreate) -> SparePart:
        self.get_product_by_id(user, product_id)
        part = SparePart(product_id=product_id, **data.model_dump())
        self.session.add(part)
        self.session.commit()
        self.session.refresh(part)
        return part

    def delete_product(self, user: User, product_id: UUID):
        """
        Deletes a product and its related associations.
        """
        product = self.get_product_by_id(user, product_id)
        # SQLAlchemy handles cascade delete based on model config
        self.session.delete(product)
        self.session.commit()

    def remove_material_link(self, user: User, product_id: UUID, material_id: UUID):
        """
        Removes a specific material from the product composition.
        """
        # 1. Security Check: Ensure User owns the Product
        self.get_product_by_id(user, product_id)

        # 2. Find the specific link
        link = self.session.exec(
            select(ProductMaterialLink).where(
                ProductMaterialLink.product_id == product_id,
                ProductMaterialLink.material_id == material_id
            )
        ).first()

        if link:
            self.session.delete(link)
            self.session.commit()

        # If link doesn't exist, we consider it "already deleted" (Idempotent success)
        return

    def remove_supplier_link(self, user: User, product_id: UUID, supplier_id: UUID):
        """
        Removes a supplier from the product. 
        Note: If a supplier has multiple roles (e.g., Tier 1 AND Tier 2), 
        this will remove ALL roles for that supplier on this product.
        """
        self.get_product_by_id(user, product_id)

        links = self.session.exec(
            select(ProductSupplierLink).where(
                ProductSupplierLink.product_id == product_id,
                ProductSupplierLink.supplier_id == supplier_id
            )
        ).all()

        if links:
            for link in links:
                self.session.delete(link)
            self.session.commit()
        return

    def remove_certification_link(self, user: User, product_id: UUID, certification_id: UUID):
        """
        Unlinks a certification from a product.
        """
        self.get_product_by_id(user, product_id)

        link = self.session.exec(
            select(ProductCertificationLink).where(
                ProductCertificationLink.product_id == product_id,
                ProductCertificationLink.certification_id == certification_id
            )
        ).first()

        if link:
            self.session.delete(link)
            self.session.commit()
        return

    def remove_spare_part(self, user: User, product_id: UUID, part_id: UUID):
        """
        Deletes a specific spare part entry.
        """
        self.get_product_by_id(user, product_id)

        part = self.session.exec(
            select(SparePart).where(
                SparePart.id == part_id,
                SparePart.product_id == product_id
            )
        ).first()

        if part:
            self.session.delete(part)
            self.session.commit()
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Spare part not found."
            )
        return
