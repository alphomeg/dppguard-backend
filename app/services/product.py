from uuid import UUID
from typing import List
from sqlmodel import Session, select
from fastapi import HTTPException

from app.db.schema import (
    User, Product, ProductVersion, VersionStatus,
    DataContributionRequest, Tenant
)
from app.models.product import ProductCreate, ProductRead


class ProductService:
    def __init__(self, session: Session):
        self.session = session

    def create_product(self, user: User, data: ProductCreate) -> ProductRead:
        tenant_id = getattr(user, "_tenant_id")

        # 1. Check SKU Uniqueness
        existing = self.session.exec(
            select(Product).where(Product.tenant_id ==
                                  tenant_id, Product.sku == data.sku)
        ).first()
        if existing:
            raise HTTPException(409, "Product with this SKU already exists.")

        # 2. Create Product Shell
        product = Product(
            tenant_id=tenant_id,
            sku=data.sku,
            gtin=data.gtin
        )
        self.session.add(product)
        self.session.flush()

        # 3. Create Version 1 (Empty Draft)
        version = ProductVersion(
            product_id=product.id,
            version_number=1,
            status=VersionStatus.WORKING_DRAFT,
            created_by_tenant_id=tenant_id,
            product_name_display=data.name,  # Name is stored in Version
            manufacturing_country=None,     # Intentionally Empty
            total_carbon_footprint_kg=None
        )
        self.session.add(version)
        self.session.commit()
        self.session.refresh(product)

        return ProductRead(
            id=product.id,
            name=version.product_name_display,
            sku=product.sku,
            gtin=product.gtin,
            latest_version_id=version.id,
            status=version.status
        )

    def list_products(self, user: User) -> List[ProductRead]:
        """
        List all products belonging to the Brand.
        We need to fetch the 'Latest Version' to show the current Status and Name.
        """
        tenant_id = getattr(user, "_tenant_id")

        # 1. Fetch Products for this Tenant
        # We assume products have at least one version (created on init).
        statement = select(Product).where(Product.tenant_id == tenant_id)
        products = self.session.exec(statement).all()

        results = []
        for product in products:
            # 2. Find Latest Version
            # Efficient way: Sort versions by number descending and take the first.
            # In a production app with huge lists, do this via SQL Join/Subquery.
            latest_version = sorted(
                product.versions, key=lambda v: v.version_number, reverse=True)[0]

            results.append(ProductRead(
                id=product.id,
                name=latest_version.product_name_display or "Untitled",
                sku=product.sku,
                gtin=product.gtin,
                latest_version_id=latest_version.id,
                status=latest_version.status
            ))

        return results

    def get_product_details(self, user: User, product_id: UUID):
        """
        Fetches the 'Command Center' data: Product + Latest Version + Active Request.
        """
        tenant_id = getattr(user, "_tenant_id")

        # 1. Fetch Product
        product = self.session.exec(
            select(Product).where(Product.id == product_id,
                                  Product.tenant_id == tenant_id)
        ).first()

        if not product:
            raise HTTPException(404, "Product not found")

        # 2. Fetch Latest Version (The one being worked on or the live one)
        # We assume the last created version is the relevant one for the UI
        version = self.session.exec(
            select(ProductVersion)
            .where(ProductVersion.product_id == product_id)
            .order_by(ProductVersion.version_number.desc())
        ).first()

        # 3. Fetch Active Request (if any) linked to this version
        # This tells us if a supplier is currently assigned
        active_request = self.session.exec(
            select(DataContributionRequest)
            .where(DataContributionRequest.current_version_id == version.id)
        ).first()

        request_status = None
        supplier_info = None

        if active_request:
            request_status = active_request.status
            # Fetch Supplier Name
            supplier_tenant = self.session.get(
                Tenant, active_request.supplier_tenant_id)
            supplier_info = {
                "id": supplier_tenant.id,
                "name": supplier_tenant.name,
                "request_id": active_request.id
            }

        # 4. Enrich Materials (Reuse logic from CollaborationService if needed)
        # (Simplified here for brevity)

        return {
            "product": product,
            "version": version,
            "materials": version.materials,
            "collaboration": {
                "status": request_status,  # SENT, SUBMITTED, etc.
                "supplier": supplier_info
            }
        }
