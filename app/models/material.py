from uuid import UUID
from sqlmodel import SQLModel, Field
from typing_extensions import Optional
from app.db.schema import MaterialType


class MaterialBase(SQLModel):
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=50,
                      description="ISO or ERP Code")
    material_type: MaterialType


class MaterialCreate(MaterialBase):
    pass


class MaterialUpdate(SQLModel):
    name: Optional[str] = None
    code: Optional[str] = None
    material_type: Optional[MaterialType] = None


class MaterialRead(MaterialBase):
    id: UUID
    tenant_id: Optional[UUID] = None  # Null if it's a system material
