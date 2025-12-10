from uuid import UUID
from sqlmodel import SQLModel, Field
from typing_extensions import Optional
from app.db.schema import RecyclabilityClass


class ProductDurabilityBase(SQLModel):
    pilling_resistance_grade: Optional[float] = Field(default=None, ge=1, le=5)
    color_fastness_grade: Optional[float] = Field(default=None, ge=1, le=5)
    dimensional_stability_percent: Optional[float] = None
    zipper_durability_cycles: Optional[int] = None
    repairability_score: Optional[float] = Field(default=None, ge=0, le=10)
    repair_instructions_url: Optional[str] = None
    recyclability_class: Optional[RecyclabilityClass] = None


class ProductDurabilityUpdate(ProductDurabilityBase):
    """Used for UPSERT (Insert or Update) on the 1-to-1 relationship."""
    pass


class ProductDurabilityRead(ProductDurabilityBase):
    product_id: UUID
