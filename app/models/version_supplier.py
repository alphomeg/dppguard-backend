from uuid import UUID
from sqlmodel import SQLModel, Field
from app.db.schema import SupplierRole


class VersionSupplierCreate(SQLModel):
    """
    Payload for a node in the supply chain graph.
    """
    supplier_id: UUID = Field(
        description="ID from the Brand's Supplier Address Book.")
    role: SupplierRole
