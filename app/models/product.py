from datetime import datetime, date
from typing import Optional, List, Dict, Any
from uuid import UUID
from sqlmodel import SQLModel, Field
from app.db.schema import VersionStatus, ProductVersionMedia, VersionMaterial, VersionSupplier, VersionCertification

# --- CREATE / UPLOAD MODELS ---


class ProductImageCreate(SQLModel):
    file_data: str = Field(description="Base64 encoded string or URL")
    is_main: bool = Field(default=False)
    display_order: int = Field(default=0)


class ProductCreate(SQLModel):
    sku: str = Field(min_length=2)
    gtin: Optional[str] = None
    name: str = Field(min_length=2)
    description: Optional[str] = None
    product_type: str
    version_name: str
    images: List[ProductImageCreate] = Field(default_factory=list)

# --- READ MODELS (Existing preserved) ---


class ProductRead(SQLModel):
    id: UUID
    tenant_id: UUID
    sku: str
    gtin: Optional[str]
    name: str
    category: str
    latest_version_id: UUID
    status: VersionStatus
    image_url: Optional[str] = None


class ProductVersionSummary(SQLModel):
    id: UUID
    version_name: str
    version_number: int
    status: VersionStatus
    created_at: datetime


class ProductDetailRead(SQLModel):
    id: UUID
    sku: str
    gtin: Optional[str]
    active_version_id: UUID
    name: str
    category: str
    description: Optional[str]
    image_url: Optional[str]
    images: List[ProductVersionMedia] = []
    materials: List[VersionMaterial] = []
    supply_chain: List[VersionSupplier] = []
    certifications: List[VersionCertification] = []
    impact: Dict[str, Any] = {}
    versions: List[ProductVersionSummary]

# --- UPDATE MODELS (New & Enhanced) ---


class VersionMetadataUpdate(SQLModel):
    """Updates Overview Tab text fields + Parent Product GTIN"""
    product_name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    version_name: Optional[str] = None
    # Allowed to update GTIN on the parent product via this route for convenience
    gtin: Optional[str] = None


class VersionImpactUpdate(SQLModel):
    """Updates Impact Tab"""
    manufacturing_country: Optional[str] = None
    total_carbon_footprint_kg: Optional[float] = None
    total_water_usage_liters: Optional[float] = None
    total_energy_mj: Optional[float] = None
    recycling_instructions: Optional[str] = None
    recyclability_class: Optional[str] = None

# -- Materials --


class MaterialAdd(SQLModel):
    material_id: Optional[UUID] = None
    name: str
    percentage: float
    origin_country: str
    transport_method: Optional[str] = "sea"


class MaterialUpdate(SQLModel):
    """New: Allows fixing typos or adjusting % on existing line items"""
    material_id: Optional[UUID] = None  # Can switch link
    name: Optional[str] = None
    percentage: Optional[float] = None
    origin_country: Optional[str] = None
    transport_method: Optional[str] = None

# -- Supply Chain --


class SupplierAdd(SQLModel):
    supplier_profile_id: Optional[UUID] = None
    name: str
    role: str
    country: str


class SupplierUpdate(SQLModel):
    """New: Allows editing a node without deleting/re-adding"""
    supplier_profile_id: Optional[UUID] = None
    name: Optional[str] = None
    role: Optional[str] = None
    country: Optional[str] = None

# -- Certifications --


class CertificationAdd(SQLModel):
    certification_id: Optional[UUID] = None
    name: str  # Fallback or display name
    document_url: Optional[str] = None
    valid_until: Optional[date] = None


class CertificationUpdate(SQLModel):
    """New: Update expiry or document URL"""
    certification_id: Optional[UUID] = None
    name: Optional[str] = None
    document_url: Optional[str] = None
    valid_until: Optional[date] = None

# -- Media --


class ProductImageAdd(SQLModel):
    """For adding a new image to an existing version"""
    file_data: str  # Base64
    is_main: bool = False
