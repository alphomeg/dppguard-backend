from typing import Optional
from uuid import UUID
from sqlmodel import SQLModel, Field
from app.db.schema import VersionStatus


class ProductCreate(SQLModel):
    """
    Payload for creating the Product Shell.
    """
    name: str = Field(min_length=2, description="Marketing Name")
    sku: str = Field(min_length=2, description="Stock Keeping Unit")
    gtin: Optional[str] = Field(default=None, description="EAN/UPC Barcode")
    description: Optional[str] = None


class ProductRead(SQLModel):
    """
    Response model for Product.
    """
    id: UUID
    name: str
    sku: str
    gtin: Optional[str]
    latest_version_id: UUID
    status: VersionStatus
