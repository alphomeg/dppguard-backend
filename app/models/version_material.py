from typing import Optional
from uuid import UUID
from sqlmodel import SQLModel, Field


class VersionMaterialCreate(SQLModel):
    """
    Payload for BOM line item.
    """
    material_id: UUID = Field(
        description="Must be a valid ID from the Material Library.")
    percentage: float
    origin_country: str = Field(min_length=2, max_length=2)
    transport_method: Optional[str] = None
    material_carbon_footprint_kg: Optional[float] = None
