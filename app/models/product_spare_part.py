from uuid import UUID
from sqlmodel import SQLModel, Field


class SparePartCreate(SQLModel):
    part_name: str = Field(min_length=1, max_length=100)
    ordering_code: str = Field(min_length=1, max_length=50)
    is_available: bool = True


class SparePartRead(SparePartCreate):
    id: UUID
    product_id: UUID
