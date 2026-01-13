from typing import Optional
from uuid import UUID
from sqlmodel import SQLModel, Field
from pydantic import EmailStr, StringConstraints, model_validator
from typing_extensions import Annotated
from datetime import datetime
from app.db.schema import ConnectionStatus, TenantType


class SupplierProfileCreate(SQLModel):
    """
    Payload for adding a new Supplier to the Brand's Address Book.
    Requires either a public handle (existing user) or an email (new invite).
    """
    name: str = Field(
        min_length=2,
        max_length=100,
        description="The internal display name you want to assign to this supplier (e.g., 'Fabric Mill A')."
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Internal notes about capabilities, contracts, or compliance status."
    )
    location_country: str = Field(
        min_length=2,
        max_length=2,
        description="ISO 2-letter country code (e.g., 'FR', 'CN'). Critical for supply chain mapping."
    )

    # Identity
    public_handle: Optional[str] = Field(
        default=None,
        description="The unique platform slug of an existing supplier (e.g., 'acme-textiles')."
    )
    invite_email: Optional[Annotated[EmailStr, StringConstraints(to_lower=True)]] = Field(
        default=None,
        description="If the supplier is not on the platform, provide their email to send an invitation."
    )
    request_note: Optional[str] = Field(
        default=None,
        max_length=500,
        description="A personal message included in the initial connection request."
    )

    @model_validator(mode='after')
    def validate_identity(self) -> 'SupplierProfileCreate':
        if not self.public_handle and not self.invite_email:
            raise ValueError(
                "You must provide either a 'public_handle' (to connect) or 'invite_email' (to invite).")
        return self


class SupplierProfileRead(SQLModel):
    """
    Response model representing a Supplier entry in the Address Book.
    """
    id: UUID = Field(description="Unique ID of the profile.")
    name: str = Field(description="Display name.")
    description: Optional[str] = Field(description="Internal notes.")
    location_country: str = Field(description="ISO country code.")

    connection_status: str = Field(
        description="Current state of the B2B handshake (e.g., Pending, Connected)."
    )

    connected_handle: Optional[str] = Field(
        default=None,
        description="If connected, the public slug of the real Supplier tenant."
    )

    audit_invite_email: Optional[str] = Field(
        default=None,
        description="The email address used for the invitation (if applicable)."
    )

    retry_count: int = Field(
        default=0,
        description="Number of times the invite has been resent."
    )

    can_reinvite: bool = Field(
        default=True,
        description="UI Helper: True if retry_count < 3 and status is not Connected."
    )


class SupplierProfileUpdate(SQLModel):
    """
    Payload for editing the alias or notes of a supplier.
    """
    name: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=100,
        description="Update the internal display name."
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Update internal notes."
    )


class SupplierReinvite(SQLModel):
    """
    Payload for re-sending an invitation.
    """
    invite_email: Optional[EmailStr] = Field(
        default=None,
        description="Optionally correct the email address if the previous one bounced."
    )
    note: Optional[str] = Field(
        default=None,
        max_length=500,
        description="A new personal message to include in the retry email."
    )


class InviteDetails(SQLModel):
    """
    Public info returned to the registration page when validating a token.
    """
    email: str
    brand_name: str
    brand_handle: str
    supplier_name: str
    supplier_country: str


class ConnectionResponse(SQLModel):
    """
    Payload for the Supplier Dashboard showing incoming requests.
    """
    connection_id: UUID
    brand_name: str
    invited_at: datetime


class DecisionPayload(SQLModel):
    """
    Action payload for accepting/declining a request.
    """
    accept: bool = Field(description="True to connect, False to decline.")


class PublicTenantRead(SQLModel):
    """
    Directory search result.
    """
    name: str
    slug: str
    type: TenantType
    location_country: str
