import uuid
from typing import List, Optional
from datetime import datetime
from sqlmodel import SQLModel, Field
from app.db.schema import ProductLifecycleStatus, MediaType

# ==========================================
# MEDIA MODELS
# ==========================================


class ProductMediaBase(SQLModel):
    """
    Shared properties for Product Media.
    """
    is_main: bool = Field(
        default=False,
        description="If True, this image becomes the cover/thumbnail for the product."
    )
    description: Optional[str] = Field(
        default=None,
        max_length=255,
        schema_extra={"examples": ["Front view of the jacket on a model."]},
        description="Alt text for accessibility and search indexing."
    )


class ProductMediaAdd(ProductMediaBase):
    """
    Payload for adding new media to a product.

    NOTE: The Brand sends a Base64 string, not a URL. 
    The backend handles uploading to storage (S3/GCS) and generating the URL.
    """
    file_data: str = Field(
        description="Base64 encoded string of the image or video file."
    )
    file_name: str = Field(
        min_length=1,
        max_length=255,
        schema_extra={"examples": ["summer_collection_v1_front.jpg"]},
        description="Original filename for reference and extension extraction."
    )
    file_type: MediaType = Field(
        default=MediaType.IMAGE,
        description="The classification of the file (e.g., IMAGE, VIDEO)."
    )


class ProductMediaReorder(SQLModel):
    """
    Payload for batch reordering media files.
    """
    media_id: uuid.UUID = Field(
        description="The unique identifier of the existing media record."
    )
    new_order: int = Field(
        ge=0,
        schema_extra={"examples": [1]},
        description="The new specific display index (0-indexed)."
    )


class ProductMediaRead(ProductMediaBase):
    """
    Response model for Product Media.
    Returns the hosted public URL rather than raw Base64 data.
    """
    id: uuid.UUID = Field(
        description="Unique identifier for the media record."
    )
    file_url: str = Field(
        description="Publicly accessible URL for the media asset."
    )
    file_name: str = Field(
        description="Original filename."
    )
    file_type: MediaType = Field(
        description="Type of media (IMAGE, VIDEO)."
    )
    display_order: int = Field(
        description="Sequence number for UI display."
    )

# ==========================================
# Create Model
# ==========================================


class ProductCreate(SQLModel):
    """
    The Master Payload to initialize a new Product.

    This creates the 'Identity' of the product (SKU, Name) and 
    simultaneously generates the first Version (Initial Release).
    """
    sku: str = Field(
        min_length=3,
        max_length=50,
        schema_extra={"examples": ["SS25-TSHIRT-ORG-001"]},
        description="Unique Stock Keeping Unit. Must be unique within the tenant."
    )
    name: str = Field(
        min_length=2,
        max_length=150,
        schema_extra={"examples": ["Organic Cotton Crew Neck T-Shirt"]},
        description="Marketing name of the product."
    )
    description: Optional[str] = Field(
        default=None,
        max_length=1000,
        schema_extra={"examples": [
            "A classic crew neck t-shirt made from 100% GOTS certified organic cotton."]},
        description="Detailed marketing description of the product."
    )

    # Optional Identifiers
    ean: Optional[str] = Field(
        default=None,
        max_length=13,
        schema_extra={"examples": ["1234567890123"]},
        description="European Article Number (13 digits)."
    )
    upc: Optional[str] = Field(
        default=None,
        max_length=12,
        schema_extra={"examples": ["123456789012"]},
        description="Universal Product Code (12 digits)."
    )
    internal_erp_id: Optional[str] = Field(
        default=None,
        max_length=100,
        schema_extra={"examples": ["ERP-998877"]},
        description="Internal system ID for mapping to legacy systems."
    )

    lifecycle_status: ProductLifecycleStatus = Field(
        default=ProductLifecycleStatus.PRE_RELEASE,
        description="Initial lifecycle status of the product identity."
    )

    # Initial Version Info
    initial_version_name: str = Field(
        min_length=2,
        max_length=100,
        schema_extra={"examples": ["SS25 Launch Batch"]},
        description="Name for the v1 release. The Brand controls this name."
    )

    # Initial Media (Optional)
    media_files: List[ProductMediaAdd] = Field(
        default_factory=list,
        description="List of initial media assets to upload."
    )

# ==========================================
# Update Model
# ==========================================


class ProductIdentityUpdate(SQLModel):
    """
    Payload for updating Product Identity details.

    NOTE: This does NOT update Version data (BOM, Operations).
    Brands cannot update the Version Name here; that is immutable after creation.
    """
    name: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=150,
        description="Update the marketing name."
    )
    description: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Update the marketing description."
    )
    ean: Optional[str] = Field(
        default=None,
        max_length=13,
        description="Update the EAN code."
    )
    upc: Optional[str] = Field(
        default=None,
        max_length=12,
        description="Update the UPC code."
    )
    lifecycle_status: Optional[ProductLifecycleStatus] = Field(
        default=None,
        description="Update the overall lifecycle status (e.g., move to ARCHIVED)."
    )

# ==========================================
# Read Model
# ==========================================


class ProductRead(SQLModel):
    """
    High-level response model for a Product.

    Returns the Identity details and a summary of the Latest Version.
    """
    id: uuid.UUID = Field(
        description="Unique Identifier for the Product Identity."
    )
    sku: str = Field(
        description="Stock Keeping Unit."
    )
    name: str = Field(
        description="Product Name."
    )
    description: Optional[str] = Field(
        default=None,
        description="Product Description."
    )
    ean: Optional[str] = Field(
        default=None,
        description="European Article Number."
    )
    upc: Optional[str] = Field(
        default=None,
        description="Universal Product Code."
    )
    lifecycle_status: ProductLifecycleStatus = Field(
        description="Current lifecycle status."
    )
    main_image_url: Optional[str] = Field(
        default=None,
        description="URL of the media item marked as 'is_main'."
    )

    # Latest/Active Version Info
    latest_version_id: Optional[uuid.UUID] = Field(
        default=None,
        description="ID of the most recently created version."
    )
    latest_version_name: Optional[str] = Field(
        default=None,
        description="Name of the most recently created version."
    )

    media: List[ProductMediaRead] = Field(
        default=[],
        description="List of associated media files."
    )

    created_at: datetime = Field(
        description="Record creation timestamp."
    )
    updated_at: datetime = Field(
        description="Last update timestamp."
    )
