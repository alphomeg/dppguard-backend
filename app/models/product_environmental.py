from uuid import UUID
from sqlmodel import SQLModel, Field
from typing_extensions import Optional


class ProductEnvironmentalBase(SQLModel):
    carbon_footprint_kg_co2e: Optional[float] = None
    water_usage_liters: Optional[float] = None
    energy_consumption_mj: Optional[float] = None
    microplastic_shedding_rate: Optional[str] = None
    substances_of_concern_present: bool = False
    soc_declaration_url: Optional[str] = None


class ProductEnvironmentalUpdate(ProductEnvironmentalBase):
    """Used for UPSERT (Insert or Update) on the 1-to-1 relationship."""
    pass


class ProductEnvironmentalRead(ProductEnvironmentalBase):
    product_id: UUID
