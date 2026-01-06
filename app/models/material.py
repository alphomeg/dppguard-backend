from typing import Optional
from uuid import UUID
from sqlmodel import SQLModel, Field
from app.db.schema import MaterialType


class MaterialCreate(SQLModel):
    """
    Payload for creating a custom material.
    """
    name: str = Field(min_length=2, max_length=100,
                      description="Material Name (e.g. Recycled Polyester)")
    code: str = Field(min_length=2, max_length=50,
                      description="Unique ERP or Standard Code")

    # NEW FIELD
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Additional details about composition, origin, etc."
    )

    material_type: MaterialType = Field(description="Category of the material")


class MaterialUpdate(SQLModel):
    """
    Payload for updating a custom material.
    """
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)

    # NEW FIELD
    description: Optional[str] = Field(default=None, max_length=500)

    # Code is usually immutable after creation to prevent breaking history,
    # but can be allowed if needed.
    material_type: Optional[MaterialType] = None


class MaterialRead(SQLModel):
    """
    Response model.
    """
    id: UUID
    name: str
    code: str

    # NEW FIELD
    description: Optional[str]

    material_type: MaterialType
    is_system: bool = Field(
        description="If True, this is a global standard and cannot be edited.")
