from sqlmodel import SQLModel, Field
from typing import Optional
import uuid
from app.db.schema import MaterialType


class MaterialDefinitionCreate(SQLModel):
    name: str = Field(min_length=2, max_length=100,
                      description="Material Name")
    code: str = Field(min_length=2, max_length=50,
                      description="Unique ERP Code")
    description: Optional[str] = Field(default=None, max_length=500)
    material_type: MaterialType = Field(default=MaterialType.OTHER)
    default_carbon_footprint: Optional[float] = Field(default=0.0)


class MaterialDefinitionUpdate(SQLModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    material_type: Optional[MaterialType] = None
    default_carbon_footprint: Optional[float] = None


class MaterialDefinitionRead(SQLModel):
    id: uuid.UUID
    name: str
    code: str
    description: Optional[str]
    material_type: MaterialType
    default_carbon_footprint: Optional[float]
    is_system: bool
