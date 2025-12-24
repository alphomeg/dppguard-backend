from typing import Optional
from uuid import UUID
from sqlmodel import SQLModel, Field
from pydantic import EmailStr, StringConstraints, model_validator
from typing_extensions import Annotated
from app.db.schema import ConnectionStatus, TenantType


class SupplierProfileCreate(SQLModel):
    """
    Input: Brand provides Name + (Handle OR Email).
    """
    name: str = Field(min_length=2, max_length=100)
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
    We restrict this to 'name' because changing the country or identity 
    (handle/email) changes the fundamental entity.
    """
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
