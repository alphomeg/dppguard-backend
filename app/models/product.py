from datetime import datetime, date
from typing import Optional, List, Dict, Any
from uuid import UUID
from sqlmodel import SQLModel, Field
from app.db.schema import VersionStatus, ProductVersionMedia, VersionMaterial, VersionSupplier, VersionCertification


class ProductImageCreate(SQLModel):
    """
    Represents an image being uploaded during creation.
    Since we are not using S3 yet, 'file_data' will hold the Base64 string.
    """
    file_data: str = Field(description="Base64 encoded string or URL")
    is_main: bool = Field(default=False)
    display_order: int = Field(default=0)


class ProductCreate(SQLModel):
    """
    Payload for creating the Product Shell + Initial Version.
    Matches the frontend Formik values.
    """
    # Immutable (Product Table)
    sku: str = Field(min_length=2, description="Stock Keeping Unit")
    gtin: Optional[str] = Field(default=None, description="EAN/UPC Barcode")

    # Mutable (Version Table)
    name: str = Field(min_length=2, description="Marketing Name")
    description: Optional[str] = None
    product_type: str = Field(description="Category (Apparel, Footwear, etc)")
    version_name: str = Field(description="e.g. 'Spring 2025 Release'")

    # Media
    images: List[ProductImageCreate] = Field(default_factory=list)


class ProductRead(SQLModel):
    """
    Response model for Product List/Details.
    Flattens the data from Product + Latest Version.
    """
    id: UUID
    tenant_id: UUID

    # From Immutable Shell
    sku: str
    gtin: Optional[str]

    # From Latest Version
    name: str             # product_name
    category: str         # category
    latest_version_id: UUID
    status: VersionStatus

    # From Latest Version Media
    image_url: Optional[str] = None  # The 'is_main' image


class ProductVersionSummary(SQLModel):
    """
    Used for the 'History' list in the frontend.
    """
    id: UUID
    version_name: str       # "Spring 2025"
    version_number: int     # 1, 2, 3
    status: VersionStatus   # "draft", "published"
    created_at: datetime


class ProductDetailRead(SQLModel):
    """
    Full Command Center View.
    Now includes rich lists (images, materials, etc.) from the active version.
    """
    id: UUID
    sku: str
    gtin: Optional[str]

    # Active/Latest Version Data
    active_version_id: UUID
    name: str
    category: str
    description: Optional[str]
    image_url: Optional[str]  # Cover image

    # --- NEW: Rich Data Lists ---
    images: List[ProductVersionMedia] = []
    materials: List[VersionMaterial] = []
    supply_chain: List[VersionSupplier] = []
    certifications: List[VersionCertification] = []
    impact: Dict[str, Any] = {}

    # Version History
    versions: List[ProductVersionSummary]

    active_request_status: Optional[str] = None


class VersionMetadataUpdate(SQLModel):
    """Update Name, Category, Description of a specific version"""
    product_name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    version_name: Optional[str] = None


class VersionImpactUpdate(SQLModel):
    """Update Environmental Stats"""
    manufacturing_country: Optional[str] = None
    total_carbon_footprint_kg: Optional[float] = None
    total_water_usage_liters: Optional[float] = None
    total_energy_mj: Optional[float] = None


class MaterialAdd(SQLModel):
    """
    If material_id is provided, we link to Library.
    If not, we use 'unlisted_material_name' as free text.
    """
    material_id: Optional[UUID] = None
    name: str  # logic: if no ID, this becomes unlisted_name
    percentage: float
    origin_country: str
    transport_method: Optional[str] = "sea"


class SupplierAdd(SQLModel):
    """
    If supplier_profile_id is provided, link to Address Book.
    Else, use free text.
    """
    supplier_profile_id: Optional[UUID] = None
    name: str  # logic: if no ID, this becomes unlisted_name
    role: str  # e.g. "tier_2_fabric"
    country: str


class CertificationAdd(SQLModel):
    certification_id: Optional[UUID] = None
    name: str
    document_url: Optional[str] = None
    valid_until: Optional[date] = None
