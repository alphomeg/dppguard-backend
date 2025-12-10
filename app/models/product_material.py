from uuid import UUID
from typing import Optional
from sqlmodel import SQLModel, Field


class ProductMaterialLinkCreate(SQLModel):
    """
    Payload for linking a material to a product.
    """
    material_id: UUID
    percentage: float = Field(
        description="Composition percentage (e.g. 95.0 for 95%).",
        ge=0, le=100
    )
    is_recycled: bool = Field(
        default=False, description="Is this specific batch recycled?")
    origin_country: Optional[str] = Field(
        default=None,
        description="Country of origin for this specific fiber usage (overrides material default)."
    )


class ProductMaterialLinkRead(ProductMaterialLinkCreate):
    """
    Read model enriched with Material Reference data.
    """
    material_name: str
    material_code: str
