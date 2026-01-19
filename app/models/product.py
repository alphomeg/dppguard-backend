from typing import Optional
from datetime import date
from uuid import UUID
from typing import List, Optional
from datetime import datetime
from sqlmodel import SQLModel, Field
from app.db.schema import ProductLifecycleStatus, MediaType, ProductVersionStatus, RequestStatus

# ==========================
# MEDIA MODELS
# ==========================


class ProductMediaBase(SQLModel):
    is_main: bool = Field(
        default=False, description="If True, this becomes the cover image.")
    description: Optional[str] = Field(
        default=None, description="Alt text for accessibility.")


class ProductMediaAdd(ProductMediaBase):
    """Input: Brand sends Base64, not a URL."""
    file_data: str = Field(
        description="Base64 encoded string of the image/video.")
    file_name: str = Field(description="Original filename for reference.")
    file_type: MediaType = Field(
        default=MediaType.IMAGE, description="image or video")


class ProductMediaReorder(SQLModel):
    """Input: Batch reordering."""
    media_id: UUID
    new_order: int


class ProductMediaRead(ProductMediaBase):
    """Output: Returns the hosted URL."""
    id: UUID
    file_url: str
    file_name: str
    file_type: MediaType
    display_order: int

# ==========================
# PRODUCT MODELS
# ==========================


class ProductCreate(SQLModel):
    """
    The Master Payload to initialize a Product.
    Includes the specific name for the first version (e.g. 'Spring Collection Launch').
    """
    sku: str = Field(min_length=3, description="Unique Stock Keeping Unit.")
    name: str = Field(description="Marketing name of the product.")
    description: Optional[str] = Field(
        default=None, description="The description of the product.")

    # Optional Identifiers
    ean: Optional[str] = Field(
        default=None, description="European Article Number.")
    upc: Optional[str] = Field(
        default=None, description="Universal Product Code.")
    internal_erp_id: Optional[str] = Field(
        default=None, description="Internal system ID.")

    lifecycle_status: ProductLifecycleStatus = Field(
        default=ProductLifecycleStatus.PRE_RELEASE,
        description="Initial lifecycle status."
    )

    # Initial Version Info (Brand controls name, not technical data)
    initial_version_name: str = Field(
        description="Name for the v1 release. Example: 'SS25 Launch Batch'"
    )

    # Initial Media (Optional)
    media_files: List[ProductMediaAdd] = Field(default_factory=list)


class ProductIdentityUpdate(SQLModel):
    """
    Brand can update Identity, but NOT Version Data.
    Brand CANNOT update Version Name here (that is immutable after creation).
    """
    name: Optional[str] = None
    description: Optional[str] = None
    ean: Optional[str] = None
    upc: Optional[str] = None
    lifecycle_status: Optional[ProductLifecycleStatus] = None


class ProductRead(SQLModel):
    """High-level view returned to Brand."""
    id: UUID
    sku: str
    name: str
    description: Optional[str]
    ean: Optional[str]
    upc: Optional[str]
    lifecycle_status: ProductLifecycleStatus
    main_image_url: Optional[str]

    # Latest/Active Version Info
    latest_version_id: Optional[UUID]
    latest_version_name: Optional[str]

    media: List[ProductMediaRead] = []
    created_at: datetime
    updated_at: datetime


class ProductAssignmentRequest(SQLModel):
    """
    Payload used by the Brand to assign a product to a specific supplier.
    This triggers the creation of a Request and potentially a new ProductVersion.
    """
    supplier_profile_id: UUID = Field(
        description="The UUID of the SupplierProfile (from the Brand's address book) to whom this request is sent."
    )

    due_date: Optional[date] = Field(
        default=None,
        description="The deadline for the supplier to submit the data."
    )

    request_note: Optional[str] = Field(
        default=None,
        description="Optional instructions or context for the supplier (e.g., 'Please focus on the carbon footprint')."
    )

# ==========================
# TECHNICAL DATA READ MODELS
# ==========================


class ProductMaterialRead(SQLModel):
    id: UUID
    material_name: str
    percentage: float
    origin_country: str
    transport_method: Optional[str]


class ProductSupplyNodeRead(SQLModel):
    id: UUID
    role: str
    company_name: str
    location_country: str


class ProductCertificateRead(SQLModel):
    id: UUID
    certificate_type_id: Optional[UUID]
    snapshot_name: str
    snapshot_issuer: str
    valid_until: Optional[date]
    file_url: str
    file_type: str


class ProductVersionDetailRead(SQLModel):
    """
    The full technical snapshot of a specific version.
    """
    id: UUID
    version_sequence: int
    version_name: str
    status: ProductVersionStatus
    created_at: datetime
    updated_at: datetime

    # Impact Data
    manufacturing_country: Optional[str]
    mass_kg: float
    total_carbon_footprint: float
    total_energy_mj: Optional[float]
    total_water_usage: Optional[float]

    # Nested Lists
    materials: List[ProductMaterialRead] = []
    supply_chain: List[ProductSupplyNodeRead] = []
    certificates: List[ProductCertificateRead] = []

# ==========================
# COLLABORATION STATUS
# ==========================


class ProductCollaborationStatusRead(SQLModel):
    """
    Summarizes the workflow state between Brand and Supplier.
    """
    active_request_id: Optional[UUID]

    product_id: UUID
    latest_version_id: Optional[UUID]

    # Workflow State
    # e.g. SENT, IN_PROGRESS, SUBMITTED
    request_status: Optional[RequestStatus] = None
    version_status: ProductVersionStatus         # e.g. DRAFT, APPROVED

    # Supplier Info
    assigned_supplier_name: Optional[str] = None
    assigned_supplier_profile_id: Optional[UUID] = None

    supplier_country: Optional[str] = None

    due_date: Optional[date] = None
    last_updated_at: datetime


class CancelRequestPayload(SQLModel):
    reason: str


class ReviewPayload(SQLModel):
    action: str  # 'approve' or 'request_changes'
    comment: Optional[str] = None
