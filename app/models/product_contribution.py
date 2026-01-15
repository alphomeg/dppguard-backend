from typing import Optional, List
from datetime import date, datetime
from uuid import UUID
from sqlmodel import SQLModel, Field
from app.db.schema import RequestStatus, ProductVersionStatus, CollaborationComment, MediaType

# ==========================
# SUB-MODELS (Nested Data)
# ==========================


class MaterialInput(SQLModel):
    name: str
    percentage: float
    origin_country: str
    transport_method: Optional[str] = None  # 'sea', 'air', 'road'


class SubSupplierInput(SQLModel):
    role: str  # 'tier_2_fabric', etc.
    name: str
    country: str


class CertificateInput(SQLModel):
    """Metadata for uploaded files (Files themselves handled separately or via separate endpoint)"""
    id: Optional[str] = None  # Frontend might send temporary ID
    name: str
    expiry_date: Optional[date] = None
    file_url: str  # Backend needs the URL after upload
    file_size_mb: Optional[str] = None

# ==========================
# MAIN DTOs
# ==========================


class TechnicalDataUpdate(SQLModel):
    """
    The Full Form Payload.
    Matches the SupplierContributionPage Formik structure.
    """
    manufacturing_country: Optional[str] = None

    # Environmental Data
    total_carbon_footprint: Optional[float] = None
    total_water_usage: Optional[float] = None  # New
    total_energy_mj: Optional[float] = None   # New

    # Nested Lists
    materials: List[MaterialInput] = []
    sub_suppliers: List[SubSupplierInput] = []

    # Note: Certificates are usually complex.
    # For simplicity, we might handle them in a separate endpoint or
    # expect them to be uploaded first, and then linked here.
    # For now, let's assume we pass a list of file references.
    certificates: List[CertificateInput] = []


class RequestReadDetail(SQLModel):
    """
    Full view for the UI.
    Includes Product Identity + Request Meta + Current Draft Data.
    """
    # Request Info
    id: UUID
    brand_name: str
    status: RequestStatus
    due_date: Optional[date]
    request_note: Optional[str]
    updated_at: datetime

    # Product Info (Read Only)
    product_name: str
    sku: str
    product_description: Optional[str]
    product_images: List[str]  # URLs
    version_name: str

    # The Form Data
    # CRITICAL FIX: The field name must be 'current_draft' to match the Service and Frontend
    current_draft: "TechnicalDataUpdate"

    # Activity Log
    history: List["ActivityLogItem"] = []


class ActivityLogItem(SQLModel):
    id: UUID
    type: str  # 'status_change', 'comment'
    title: str
    date: datetime
    user_name: str
    note: Optional[str] = None


# ==========================
# WORKFLOW DTOS
# ==========================


class RequestAction(SQLModel):
    """Payload for changing status (Accept/Decline/Submit)."""
    action: str = Field(description="Values: 'accept', 'decline', 'submit'")
    note: Optional[str] = Field(
        default=None, description="Optional reason or comment.")


class CommentRead(SQLModel):
    id: UUID
    author_name: str
    body: str
    created_at: datetime


class RequestReadList(SQLModel):
    """Row item for the Supplier Dashboard."""
    id: UUID
    brand_name: str
    product_name: str
    product_image_url: Optional[str] = None
    sku: str
    version_name: str
    due_date: Optional[date]
    status: RequestStatus
    updated_at: datetime
