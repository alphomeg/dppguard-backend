from typing import Optional
from uuid import UUID
from sqlmodel import SQLModel, Field
from pydantic import EmailStr, StringConstraints, model_validator
from typing_extensions import Annotated
from app.db.schema import ConnectionStatus, TenantType
from datetime import datetime


class SupplierProfileCreate(SQLModel):
    """
    Input: Brand provides Name + (Handle OR Email).
    """
    name: str = Field(min_length=2, max_length=100)

    # NEW FIELD
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Internal notes, capabilities, or details about this supplier."
    )

    location_country: str = Field(min_length=2, max_length=2)

    # Identification Options
    public_handle: Optional[str] = Field(
        default=None,
        description="Connect to an existing company (e.g., 'pk-textiles')."
    )
    invite_email: Optional[Annotated[EmailStr, StringConstraints(to_lower=True)]] = Field(
        default=None,
        description="Invite a new company via email."
    )
    request_note: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Personal message to include in the email."
    )

    @model_validator(mode='after')
    def validate_identity(self) -> 'SupplierProfileCreate':
        if not self.public_handle and not self.invite_email:
            raise ValueError(
                "Provide either 'public_handle' or 'invite_email'.")
        return self


class SupplierProfileRead(SQLModel):
    """
    Output: The Profile View.
    """
    id: UUID
    name: str

    # NEW FIELD
    description: Optional[str]

    location_country: str

    # Computed / Joined Fields
    connection_status: ConnectionStatus

    # If Connected -> Show Handle
    connected_handle: Optional[str] = None

    # If Pending/Invite -> Show Email (Audit)
    audit_invite_email: Optional[str] = None


class PublicTenantRead(SQLModel):
    """Minimal view of a tenant for directory search."""
    name: str
    slug: str
    type: TenantType
    location_country: str


class SupplierProfileUpdate(SQLModel):
    """
    Payload for updating a supplier alias.
    We restrict this to 'name' and 'description' because changing the country or identity 
    (handle/email) changes the fundamental entity.
    """
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)

    # NEW FIELD
    description: Optional[str] = Field(default=None, max_length=500)


class InviteDetails(SQLModel):
    """
    Data returned to the frontend when a user clicks an invite link.
    """
    email: str
    brand_name: str
    brand_handle: str

    # --- NEW FIELDS ---
    # The name the Brand assigned to you (e.g. "Lahore Fabrics")
    supplier_name: str
    supplier_country: str   # The country the Brand assigned


class ConnectionResponse(SQLModel):
    connection_id: UUID
    brand_name: str
    invited_at: datetime


class DecisionPayload(SQLModel):
    accept: bool


class SupplierReinvite(SQLModel):
    """
    Payload for re-sending an invitation.
    Allows correcting the email or adding a note.
    """
    invite_email: Optional[EmailStr] = Field(
        default=None,
        description="Correct the email address if it was wrong."
    )
    note: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Personal message to include in the email."
    )
