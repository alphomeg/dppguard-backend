import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field
from app.db.schema import MaterialType

# ==========================================
# Create Model
# ==========================================


class MaterialDefinitionCreate(SQLModel):
    """
    Payload for creating a new Material Definition.

    NOTE: This action is restricted to Supplier Tenants. 
    System materials are seeded via administrative scripts, not this API.
    """
    name: str = Field(
        min_length=2,
        max_length=100,
        schema_extra={"examples": ["Recycled Polyester Blend A"]},
        description="The common, human-readable name of the material."
    )
    code: str = Field(
        min_length=2,
        max_length=50,
        schema_extra={"examples": ["MAT-RPOLY-001"]},
        description="Internal ERP code, SKU, or ISO standard code. Must be unique within the tenant."
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        schema_extra={"examples": [
            "95% Recycled Polyester, 5% Elastane from post-consumer waste."]},
        description="Detailed composition or sourcing notes."
    )
    material_type: MaterialType = Field(
        default=MaterialType.OTHER,
        description="The categorization of the material (e.g., FABRIC, METAL, PLASTIC)."
    )
    default_carbon_footprint: Optional[float] = Field(
        default=0.0,
        ge=0.0,
        description="Baseline CO2e emissions per unit (usually per kg) for this specific material batch."
    )

# ==========================================
# Update Model
# ==========================================


class MaterialDefinitionUpdate(SQLModel):
    """
    Payload for updating an existing Material Definition.

    Only the owner (Supplier Tenant) can update their own definitions.
    System/Global definitions are read-only for tenants.
    """
    name: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=100,
        description="Update the material name."
    )
    code: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=50,
        description="Update the internal ERP code."
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Update composition details."
    )
    material_type: Optional[MaterialType] = Field(
        default=None,
        description="Update the material category."
    )
    default_carbon_footprint: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Update the baseline CO2e value."
    )

# ==========================================
# Read Model
# ==========================================


class MaterialDefinitionRead(SQLModel):
    """
    Response model for returning Material Definitions.

    Includes flags to indicate if the material is a Global System Standard
    or a Supplier-specific definition.
    """
    id: uuid.UUID = Field(
        description="Unique Identifier for the material definition.")
    name: str = Field(description="Material Name.")
    code: str = Field(description="Material Code.")
    description: Optional[str] = Field(
        default=None, description="Material Details.")
    material_type: MaterialType = Field(description="Category of material.")
    default_carbon_footprint: Optional[float] = Field(
        description="CO2e per kg.")

    # TimestampMixin fields (Assuming you want to expose when it was defined)
    created_at: Optional[datetime] = Field(
        default=None, description="Record creation timestamp.")
    updated_at: Optional[datetime] = Field(
        default=None, description="Last update timestamp.")

    # Computed/Logic fields
    is_system: bool = Field(
        description="True if this is a Global Standard material; False if it belongs to a specific Supplier."
    )
