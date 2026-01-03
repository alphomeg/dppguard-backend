from typing import List
from uuid import UUID
from sqlmodel import Session, select
from app.db.schema import (
    User, DataContributionRequest, RequestStatus,
    ProductVersion, Product, Tenant, SupplierProfile
)

from app.models.dashboard import ProductTaskItem


class BrandService:
    def __init__(self, session: Session):
        self.session = session

    def get_pending_reviews(self, user: User) -> List[dict]:
        """
        Fetch all Data Requests that are in 'SUBMITTED' state for this Brand.
        """
        brand_id = getattr(user, "_tenant_id")

        # Join: Request -> Version -> Product -> Supplier Tenant
        statement = (
            select(DataContributionRequest, ProductVersion, Product, Tenant)
            .join(ProductVersion, DataContributionRequest.current_version_id == ProductVersion.id)
            .join(Product, ProductVersion.product_id == Product.id)
            # The Supplier
            .join(Tenant, DataContributionRequest.supplier_tenant_id == Tenant.id)
            .where(DataContributionRequest.brand_tenant_id == brand_id)
            .where(DataContributionRequest.status == RequestStatus.SUBMITTED)
            .order_by(DataContributionRequest.updated_at.desc())
        )

        results = self.session.exec(statement).all()

        reviews = []
        for req, version, product, supplier_tenant in results:
            reviews.append({
                "request_id": req.id,
                "product_name": version.product_name_display,
                "sku": product.sku,
                "supplier_name": supplier_tenant.name,  # The real tenant name
                "submitted_at": req.updated_at,
                "status": req.status
            })

        return reviews
