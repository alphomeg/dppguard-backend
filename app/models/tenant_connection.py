from uuid import UUID
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field
from pydantic import EmailStr
from app.db.schema import TenantType, RelationshipType


class ConnectionReinvite(SQLModel):
    """
    Payload for re-sending an invitation to a pending connection (Supplier, Recycler, etc.).
    """
    invite_email: Optional[EmailStr] = Field(
        default=None,
        schema_extra={"examples": ["contact@partner-company.com"]},
        description="Optionally correct the email address if the previous one bounced."
    )
    note: Optional[str] = Field(
        default=None,
        max_length=500,
        schema_extra={"examples": [
            "Apologies, we had the wrong email. Please join us."]},
        description="A new personal message to include in the retry email."
    )


class InviteDetails(SQLModel):
    """
    Public info returned to the frontend when a user clicks an email link.
    Now supports polymorphic profiles (Supplier, Recycler, etc.) and generic Requesters.
    """
    # Common Connection Data
    email: str = Field(
        description="The email address that was originally invited.")
    request_note: Optional[str] = Field(
        description="Personal message from the requester.")

    # Requester Data (Renamed from 'brand' to 'requester')
    requester_name: str = Field(
        description="Name of the Tenant sending the invite (e.g., The Brand or The Supplier)."
    )
    requester_handle: str = Field(
        description="Platform slug of the Requester."
    )

    # Target (Invitee) Data
    relationship_type: RelationshipType = Field(
        description="The role the requester wants you to fulfill (e.g. SUPPLIER, RECYCLER)."
    )
    target_name: str = Field(
        description="The internal name the Requester assigned to this partner."
    )
    target_country: Optional[str] = Field(
        default=None,
        description="The expected country of the partner."
    )

    # Flexible payload for type-specific data
    # If type=SUPPLIER, might contain {"contact_name": "..."}
    profile_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Type-specific details about the profile entry."
    )


class PublicTenantRead(SQLModel):
    """
    Directory search result for the 'Connect to Existing' feature.
    """
    id: UUID = Field(description="Tenant ID.")
    name: str = Field(description="Official Company Name.")
    slug: str = Field(description="Unique Platform Handle.")
    type: TenantType = Field(
        description="The role of this tenant (Brand, Supplier, Recycler).")
    location_country: str = Field(description="ISO Country Code.")
