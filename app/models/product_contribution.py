import uuid
from datetime import date, datetime
from typing import List, Optional
from sqlmodel import SQLModel, Field
from app.db.schema import RequestStatus, ProductVersionStatus

# ==========================================
# SUB-MODELS (Nested Data Inputs)
# ==========================================


class MaterialInput(SQLModel):
    """
    Represents a single row in the Bill of Materials (BOM) input form.
    """
    lineage_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Include when editing existing material. Omit for new materials."
    )
    source_material_definition_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Link to the MaterialDefinition from the supplier's material library. If this material was selected from the supplier's library of material definitions, provide the MaterialDefinition ID here. If creating a new material entry, leave null."
    )
    name: str = Field(
        min_length=2,
        max_length=100,
        schema_extra={"examples": ["Recycled Polyester"]},
        description="Name of the material component."
    )
    percentage: float = Field(
        ge=0.0,
        le=100.0,
        schema_extra={"examples": [45.5]},
        description="Composition percentage (0-100)."
    )
    origin_country: str = Field(
        min_length=2,
        max_length=100,
        schema_extra={"examples": ["Turkey"]},
        description="Country where the material was sourced."
    )
    transport_method: Optional[str] = Field(
        default=None,
        max_length=50,
        schema_extra={"examples": ["SEA", "AIR", "ROAD"]},
        description="Primary mode of transport for this material."
    )


class SubSupplierInput(SQLModel):
    """
    Represents a specific node in the supply chain (Tier 2/3).
    """
    lineage_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Include when editing existing supply node. Omit for new nodes."
    )
    role: str = Field(
        min_length=2,
        max_length=100,
        schema_extra={"examples": ["Fabric Mill", "Dye House"]},
        description="The function this supplier performs."
    )
    name: str = Field(
        min_length=2,
        max_length=150,
        schema_extra={"examples": ["Textile Corp Ltd."]},
        description="Company name of the sub-supplier."
    )
    country: str = Field(
        min_length=2,
        max_length=100,
        schema_extra={"examples": ["Portugal"]},
        description="Location of the facility."
    )


class CertificateInput(SQLModel):
    """
    Represents a certificate attached to the technical version.
    Includes support for existing files (file_url) or new uploads (temp_file_id).
    Note: issuer is automatically fetched from certificate_type_id -> issuer_authority, not provided by frontend.
    """
    id: Optional[str] = Field(
        default=None,
        description="If editing, this is the existing ID. If new, leave null."
    )
    lineage_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Include when editing existing certificate. Omit for new certificates."
    )
    certificate_type_id: uuid.UUID = Field(
        description="UUID of the standard certificate definition (e.g. GOTS, Oeko-Tex)."
    )
    source_artifact_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Link to the SupplierArtifact (file) from the supplier's vault/library. This is the file/artifact that the supplier uploaded. If the certificate file was selected from the supplier's library, provide the SupplierArtifact ID here. If uploading a new file via temp_file_id, this will be automatically set to the newly created artifact."
    )
    name: str = Field(
        min_length=2,
        max_length=100,
        schema_extra={"examples": ["GOTS - 2024 Audit"]},
        description="Display name or snapshot reference for this specific document."
    )
    issuer: Optional[str] = Field(
        default=None,
        description="READ-ONLY: Issuer is automatically populated from certificate definition. Not accepted as input."
    )
    expiry_date: Optional[date] = Field(
        default=None,
        description="When this specific certificate expires."
    )
    file_url: Optional[str] = Field(
        default=None,
        description="URL if the file is already uploaded."
    )
    file_name: Optional[str] = Field(
        default=None,
        description="The original filename with extension (e.g., 'certificate.pdf'). When updating an existing certificate, include this to preserve the file extension. If omitted, the backend will preserve the existing filename."
    )
    file_size_bytes: Optional[int] = Field(
        default=None,
        description="READ-ONLY: The file size in bytes. Returned by the backend but not accepted as input."
    )
    temp_file_id: Optional[str] = Field(
        default=None,
        description="The ID returned by the upload endpoint if this is a new file being attached. This should match the filename of one of the files in the multipart/form-data upload."
    )


# ==========================================
# WRITE MODELS (Action Payloads)
# ==========================================


class TechnicalDataUpdate(SQLModel):
    """
    The Full Form Payload for the Supplier Contribution Page.
    Parses the massive JSON form used to update the draft.
    """
    manufacturing_country: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Where final assembly occurred."
    )

    # Environmental Data
    total_carbon_footprint: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Total CO2e emissions (kg) for this specific batch/unit."
    )
    total_water_usage: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Total water consumption (liters)."
    )
    total_energy_mj: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Total energy usage (MJ)."
    )

    # Nested Lists
    materials: List[MaterialInput] = Field(
        default=[],
        description="List of materials composing the product."
    )
    sub_suppliers: List[SubSupplierInput] = Field(
        default=[],
        description="List of supply chain nodes."
    )
    certificates: List[CertificateInput] = Field(
        default=[],
        description="List of certifications attached."
    )


class RequestAction(SQLModel):
    """
    Payload for changing the workflow state of a request.
    """
    action: str = Field(
        schema_extra={"examples": ["accept", "decline", "submit"]},
        description="The command to execute: 'accept', 'decline', or 'submit'."
    )
    note: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional reason or context (e.g., reason for declining)."
    )


class ProductAssignmentRequest(SQLModel):
    """
    Payload used by the Brand to assign a product to a specific supplier.
    Triggers creation of a Request and a ProductVersion.
    """
    supplier_profile_id: uuid.UUID = Field(
        description="The UUID of the SupplierProfile (from Brand's address book) to receive this request."
    )
    version_name: str = Field(
        min_length=2,
        max_length=100,
        schema_extra={"examples": ["SS25 Launch Batch", "Lot 405"]},
        description="Name for this version/batch. Can be duplicate across different requests."
    )
    due_date: Optional[date] = Field(
        default=None,
        description="The deadline for submission."
    )
    request_note: Optional[str] = Field(
        default=None,
        max_length=1000,
        schema_extra={"examples": [
            "Please focus on the carbon footprint data."]},
        description="Instructions for the supplier."
    )


class CancelRequestPayload(SQLModel):
    """Payload for canceling an active request."""
    reason: str = Field(
        min_length=5,
        max_length=500,
        description="Reason for cancellation."
    )


class ReviewPayload(SQLModel):
    """Payload for Brand reviewing a submission."""
    action: str = Field(
        description="One of: 'approve', 'request_changes'."
    )
    comment: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Feedback to the supplier if requesting changes."
    )


# ==========================================
# READ MODELS (Response DTOs)
# ==========================================


class ActivityLogItem(SQLModel):
    """
    A single entry in the collaboration history timeline.
    """
    id: uuid.UUID = Field(description="Unique ID of the log entry.")
    type: str = Field(
        description="Event type (e.g. 'status_change', 'comment').")
    title: str = Field(description="Short headline for the event.")
    date: datetime = Field(description="Timestamp of the event.")
    user_name: str = Field(description="Name of the actor.")
    note: Optional[str] = Field(
        default=None, description="Additional context or message body.")


class RequestReadDetail(SQLModel):
    """
    Full Context View for the Supplier Contribution Page.
    Combines Request Metadata, Product Identity, and Draft Data.
    """
    # Request Info
    id: uuid.UUID = Field(description="Unique Request ID.")
    brand_name: str = Field(description="Name of the Brand requesting data.")
    status: RequestStatus = Field(description="Current status of the request.")
    due_date: Optional[date] = Field(description="Submission deadline.")
    request_note: Optional[str] = Field(description="Initial instructions/comment from Brand when creating the request.")
    created_at: datetime = Field(description="When the request was created.")
    updated_at: datetime = Field(description="Last modification time.")

    # Product Info (Read Only)
    product_name: str = Field(description="Marketing Name.")
    sku: str = Field(description="Stock Keeping Unit.")
    product_description: Optional[str] = Field(
        description="Product description.")
    product_images: List[str] = Field(
        description="List of product image URLs.")
    version_name: str = Field(
        description="Name of the batch/version being edited.")

    # The Form Data
    current_draft: TechnicalDataUpdate = Field(
        description="The current state of the form data (BOM, Impacts, etc)."
    )

    # Activity Log
    history: List[ActivityLogItem] = Field(
        default=[],
        description="Timeline of actions and comments."
    )


class RequestReadList(SQLModel):
    """
    Summary Row for the Supplier Dashboard List.
    """
    id: uuid.UUID = Field(description="Request ID.")
    brand_name: str = Field(description="Brand Name.")
    product_name: str = Field(description="Product Name.")
    product_description: Optional[str] = Field(
        default=None, description="Product description for supplier to review.")
    product_image_url: Optional[str] = Field(
        default=None, description="Thumbnail URL.")
    sku: str = Field(description="SKU.")
    version_name: str = Field(description="Version/Batch Name.")
    due_date: Optional[date] = Field(default=None, description="Deadline.")
    request_note: Optional[str] = Field(
        default=None, description="Initial instructions/comment from Brand when creating the request.")
    status: RequestStatus = Field(description="Current Workflow Status.")
    updated_at: datetime = Field(description="Last update timestamp.")


class ProductMaterialRead(SQLModel):
    id: uuid.UUID
    lineage_id: uuid.UUID
    material_name: str
    percentage: float
    origin_country: str
    transport_method: Optional[str]


class ProductSupplyNodeRead(SQLModel):
    id: uuid.UUID
    lineage_id: uuid.UUID
    role: str
    company_name: str
    location_country: str


class ProductCertificateRead(SQLModel):
    id: uuid.UUID
    lineage_id: uuid.UUID
    certificate_type_id: Optional[uuid.UUID]
    snapshot_name: str
    snapshot_issuer: str
    valid_until: Optional[date]
    file_url: str
    file_type: str
    file_size_bytes: Optional[int] = None


class ProductVersionDetailRead(SQLModel):
    """
    The full technical snapshot of a specific version.
    Used by Brands to view the submitted data.
    """
    id: uuid.UUID
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


class ProductCollaborationStatusRead(SQLModel):
    """
    Summarizes the workflow state between Brand and Supplier.
    """
    active_request_id: Optional[uuid.UUID] = Field(
        description="If there is an open request, this is its ID."
    )

    product_id: uuid.UUID
    latest_version_id: Optional[uuid.UUID]

    # Workflow State
    request_status: Optional[RequestStatus] = Field(
        default=None, description="Status of the communication channel (SENT, ACCEPTED)."
    )
    version_status: ProductVersionStatus = Field(
        description="Status of the data itself (DRAFT, APPROVED)."
    )

    # Supplier Info
    assigned_supplier_name: Optional[str] = None
    assigned_supplier_profile_id: Optional[uuid.UUID] = None
    supplier_country: Optional[str] = None

    due_date: Optional[date] = None
    last_updated_at: datetime
    
    # Notes/Reasons
    decline_reason: Optional[str] = Field(
        default=None,
        description="Reason provided by supplier when declining the request."
    )


# ==========================================
# COMPARISON MODELS
# ==========================================


class VersionComparisonMaterial(ProductMaterialRead):
    pass  # Inherits lineage_id for matching


class VersionComparisonSupply(ProductSupplyNodeRead):
    pass  # Inherits lineage_id for matching


class VersionComparisonImpact(SQLModel):
    id: str = Field(description="Internal key for display logic")
    label: str
    val: str = Field(description="Formatted value with unit (e.g., '4.5 kg')")


class VersionComparisonCertificate(ProductCertificateRead):
    pass  # Inherits lineage_id for matching


class VersionComparisonSnapshot(SQLModel):
    """
    A flattened view of a single version for side-by-side UI.
    """
    version_label: str
    version_sequence: int = Field(
        description="The major version number (e.g., 1, 2, 3)."
    )
    revision: int = Field(
        description="Highest revision number in this sequence."
    )
    materials: List[VersionComparisonMaterial] = []
    supply_chain: List[VersionComparisonSupply] = []
    impact: List[VersionComparisonImpact] = []
    certificates: List[VersionComparisonCertificate] = []


class VersionComparisonResponse(SQLModel):
    """
    The wrapper for the comparison view.
    """
    previous: Optional[VersionComparisonSnapshot] = Field(
        default=None, description="The baseline version (or older version)."
    )
    current: VersionComparisonSnapshot = Field(
        description="The active version being edited/reviewed."
    )
