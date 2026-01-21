from typing import Optional
from uuid import UUID
from datetime import datetime
from sqlmodel import SQLModel, Field
from pydantic import EmailStr, model_validator, computed_field
from app.db.schema import ConnectionStatus

# ==========================================
# Create Model
# ==========================================


class SupplierProfileCreate(SQLModel):
    """
    Payload for adding a new Supplier to the Brand's Address Book.

    This handles two scenarios:
    1. CONNECT: Connecting to an existing Supplier on the platform (via `public_handle`).
    2. INVITE: Onboarding a new Supplier via email (via `invite_email`).
    """
    name: str = Field(
        min_length=2,
        max_length=100,
        schema_extra={"examples": ["Orion Fabrics Ltd."]},
        description="The internal display name you want to assign to this supplier."
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        schema_extra={"examples": [
            "Primary supplier for Denim lines. ISO 14001 certified."]},
        description="Internal notes about capabilities, contracts, or compliance status."
    )
    location_country: str = Field(
        min_length=2,
        max_length=2,
        schema_extra={"examples": ["FR", "CN", "TR"]},
        description="ISO 3166-1 alpha-2 country code. Critical for supply chain geo-fencing."
    )

    # Address Book Contact Info
    contact_email: Optional[EmailStr] = Field(
        default=None,
        description="Point of Contact email (e.g., 'john.doe@company.com')."
    )

    contact_name: Optional[str] = Field(
        default=None,
        description="Point of Contact name (e.g., 'John Doe')."
    )

    is_favorite: Optional[bool] = Field(
        default=False,
        description="Mark this supplier as a favorite for easy access in the UI."
    )

    # Identity / Connection Logic
    public_handle: Optional[str] = Field(
        default=None,
        schema_extra={"examples": ["acme-textiles-global"]},
        description="The unique platform slug of an existing supplier. If provided, a connection request is sent immediately."
    )
    invite_email: Optional[EmailStr] = Field(
        default=None,
        schema_extra={"examples": ["sales@company.com"]},
        description="If the supplier is not on the platform, provide their email to send an onboarding invitation."
    )
    request_note: Optional[str] = Field(
        default=None,
        max_length=500,
        description="A personal message included in the initial connection request email/notification."
    )

    @model_validator(mode='after')
    def validate_identity(self) -> 'SupplierProfileCreate':
        """
        Ensure strictly one connection method is provided:
        - Either Connect via Handle
        - OR Invite via Email
        """
        # 1. Check if NEITHER is provided
        if not self.public_handle and not self.invite_email:
            raise ValueError(
                "You must provide either a 'public_handle' (to connect) or 'invite_email' (to invite)."
            )

        # 2. Check if BOTH are provided (Mutually Exclusive)
        if self.public_handle and self.invite_email:
            raise ValueError(
                "You cannot provide both a 'public_handle' and an 'invite_email'. "
                "Please choose only one method: connect to an existing user OR invite a new one."
            )

        return self


# ==========================================
# Update Model
# ==========================================
class SupplierProfileUpdate(SQLModel):
    """
    Payload for editing the Address Book entry.
    These changes only affect the Brand's view, not the Supplier's actual profile.
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
    contact_name: Optional[str] = Field(
        default=None,
        description="Update the point of contact name."
    )
    contact_email: Optional[EmailStr] = Field(
        default=None,
        description="Update the saved contact email (does not re-send invites)."
    )
    is_favorite: Optional[bool] = Field(
        default=None,
        description="Toggle 'Star/Favorite' status for UI sorting."
    )


# ==========================================
# Read Model
# ==========================================
class SupplierProfileRead(SQLModel):
    """
    Response model representing a Supplier entry in the Address Book.
    Aggregates data from 'SupplierProfile' and 'TenantConnection'.
    """
    id: UUID = Field(description="Unique ID of the profile (Address Book ID).")

    # Profile Data
    name: str = Field(description="Display name.")
    description: Optional[str] = Field(description="Internal notes.")
    location_country: str = Field(description="ISO country code.")
    contact_name: Optional[str] = Field(description="Point of Contact.")
    contact_email: Optional[str] = Field(description="Contact Email.")
    is_favorite: bool = Field(description="Is marked as favorite.")

    # Connection State (Computed from TenantConnection relationship)
    connection_status: ConnectionStatus = Field(
        description="Current state of the B2B handshake."
    )
    connected_handle: Optional[str] = Field(
        default=None,
        description="If status is CONNECTED, this is the public slug of the real Supplier."
    )

    # Audit / Invitation Info
    audit_invite_email: Optional[str] = Field(
        default=None,
        description="The specific email address the invitation was sent to."
    )
    retry_count: int = Field(
        default=0,
        description="Number of times the invite has been resent."
    )

    created_at: datetime = Field(description="When this supplier was added.")
    updated_at: datetime = Field(description="Last update.")

    # ==========================================
    # COMPUTED FIELDS
    # ==========================================
    @computed_field
    def can_reinvite(self) -> bool:
        """
        UI Helper: True if the invite is pending/rejected and retry limit not reached.
        """
        # Logic matches your requirement: PENDING or REJECTED + Retry Count < 3
        is_retryable_status = self.connection_status in [
            ConnectionStatus.PENDING,
            ConnectionStatus.REJECTED
        ]
        return is_retryable_status and self.retry_count < 3
