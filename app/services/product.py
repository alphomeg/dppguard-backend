from uuid import UUID
from fastapi import HTTPException, status
from sqlmodel import Session, select
from sqlalchemy.orm import selectinload
from loguru import logger

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
    """
    Service layer for managing Clothing Products and their Digital Product Passport (DPP) data.

    Handles:
    - Core Product Lifecycle (Create, Update, List)
    - ESPR Extensions (Durability, Environmental Footprint)
    - Supply Chain Linking (Materials, Suppliers, Certifications)
    """

    def __init__(self, session: Session):
        self.session = session

    def get_product_by_id(self, user: User, product_id: UUID) -> Product:
        """
        Internal helper to fetch a product and verify tenant ownership.
        """
        product = self.session.exec(
            select(Product).where(
                Product.id == product_id,
                Product.tenant_id == user.tenant_id
            )
        ).first()

        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found."
            )
        return product

    def create_product(self, user: User, data: ProductCreate) -> Product:
        """
        Creates the basic product shell (SKU, Name, Batch).
        """
        if data.gtin:
            existing = self.session.exec(
                select(Product).where(Product.gtin == data.gtin,
                                      Product.tenant_id == user.tenant_id)
            ).first()
            if existing:
                raise HTTPException(
                    status_code=409, detail=f"Product with GTIN {data.gtin} already exists.")

        product = Product(**data.model_dump(), tenant_id=user.tenant_id)
        self.session.add(product)
        self.session.commit()
        self.session.refresh(product)
        return product

    def update_product(self, user: User, product_id: UUID, data: ProductUpdate) -> Product:
        """
        Updates basic product information.
        """
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

        This method performs Eager Loading to fetch all related tables (materials, 
        suppliers, extensions) in an optimized way to prevent N+1 query problems.
        """

        # Eager load all relationships
        query = (
            select(Product)
            .where(Product.id == product_id, Product.tenant_id == user.tenant_id)
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

        # TRANSFORM: Map DB Models to API Read Models (Enriching IDs with Names)

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

        # Construct the Composite DTO
        return ProductFullDetailsRead(
            **product.model_dump(),
            created_at=product.created_at,
            updated_at=product.updated_at,
            durability=product.durability,
            environmental=product.environmental,
            materials=material_dtos,
            suppliers=supplier_dtos,
            certifications=cert_dtos,
            spare_parts=[SparePartRead.model_validate(
                p) for p in product.spare_parts]
        )

    def upsert_durability(self, user: User, product_id: UUID, data: ProductDurabilityUpdate) -> ProductDurability:
        """
        Creates or Updates the 1-to-1 Durability record.
        """
        # Ensure product exists and belongs to user
        self.get_product_by_id(user, product_id)

        # Check existing extension record
        durability_record = self.session.exec(
            select(ProductDurability).where(
                ProductDurability.product_id == product_id)
        ).first()

        if durability_record:
            # Update existing
            for key, value in data.model_dump(exclude_unset=True).items():
                setattr(durability_record, key, value)
        else:
            # Create new
            durability_record = ProductDurability(
                product_id=product_id,
                **data.model_dump()
            )

        self.session.add(durability_record)
        self.session.commit()
        self.session.refresh(durability_record)
        return durability_record

    def upsert_environmental(self, user: User, product_id: UUID, data: ProductEnvironmentalUpdate) -> ProductEnvironmental:
        """
        Creates or Updates the 1-to-1 PEF record.
        """
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
        Links a material to the product. Checks total composition logic could go here.
        """
        product = self.get_product_by_id(user, product_id)
        tenant_id = product.tenant_id

        # Validate Material exists and is accessible
        material = self.session.exec(select(Material).where(
            Material.id == data.material_id)).first()
        if not material:
            raise HTTPException(status_code=404, detail="Material not found")

        # Access Check: Material must be Global or belong to Tenant
        if material.tenant_id and material.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403, detail="Cannot access this material")

        # Check if already linked
        existing_link = self.session.exec(
            select(ProductMaterialLink).where(
                ProductMaterialLink.product_id == product_id,
                ProductMaterialLink.material_id == data.material_id
            )
        ).first()

        if existing_link:
            # Update existing percentage if trying to add again
            existing_link.percentage = data.percentage
            existing_link.is_recycled = data.is_recycled
            existing_link.origin_country = data.origin_country
            self.session.add(existing_link)
        else:
            # Create new link
            new_link = ProductMaterialLink(
                product_id=product_id, **data.model_dump())
            self.session.add(new_link)

        self.session.commit()
        return {"status": "linked", "material_id": data.material_id}

    def add_supplier_link(self, user: User, product_id: UUID, data: ProductSupplierLinkCreate):
        product = self.get_product_by_id(user, product_id)

        # Verify supplier ownership
        supplier = self.session.exec(
            select(Supplier).where(
                Supplier.id == data.supplier_id,
                Supplier.tenant_id == product.tenant_id
            )
        ).first()

        if not supplier:
            raise HTTPException(
                status_code=404, detail="Supplier not found or access denied")

        # Create Link
        link = ProductSupplierLink(product_id=product_id, **data.model_dump())
        self.session.add(link)

        try:
            self.session.commit()
        except Exception:
            # Likely duplicate PK constraint if user tries to add same supplier twice
            self.session.rollback()
            raise HTTPException(
                status_code=409, detail="Supplier already linked to this product.")

        return {"status": "linked", "supplier_id": data.supplier_id}

    def add_certification_link(self, user: User, product_id: UUID, data: ProductCertificationLinkCreate):
        self.get_product_by_id(user, product_id)
        # Create Link
        link = ProductCertificationLink(
            product_id=product_id, **data.model_dump())
        self.session.add(link)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise HTTPException(
                status_code=409, detail="Certification already linked to this product.")

        return {"status": "linked", "certification_id": data.certification_id}

    def add_spare_part(self, user: User, product_id: UUID, data: SparePartCreate) -> SparePart:
        self.get_product_by_id(user, product_id)
        part = SparePart(product_id=product_id, **data.model_dump())
        self.session.add(part)
        self.session.commit()
        self.session.refresh(part)
        return part
