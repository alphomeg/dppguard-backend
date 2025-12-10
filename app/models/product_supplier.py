from uuid import UUID
from sqlmodel import SQLModel, Field
from app.db.schema import SupplierRole


class ProductSupplierLinkCreate(SQLModel):
    """
    Payload for linking a supplier to a product.
    """
    supplier_id: UUID
    role: SupplierRole = Field(
        description="The tier/role this supplier performs.")


class ProductSupplierLinkRead(ProductSupplierLinkCreate):
    """
    Read model enriched with Supplier Reference data.
    """
    supplier_name: str
    supplier_country: str
