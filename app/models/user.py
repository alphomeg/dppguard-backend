from enum import Enum
from typing import Optional
from uuid import UUID
from sqlmodel import SQLModel, Field
from pydantic import EmailStr, StringConstraints
from typing_extensions import Annotated

from app.db.schema import TenantType


class RegistrationTenantType(str, Enum):
    """
    Restricted Tenant Types allowed during public registration.
    (System Admins cannot self-register).
    """
    BRAND = TenantType.BRAND.value
    SUPPLIER = TenantType.SUPPLIER.value


# ==========================================
# Read / Response Models
# ==========================================

class ActiveTenantRead(SQLModel):
    """
    Lightweight representation of the User's current context.
    """
    id: UUID = Field(description="The active Tenant ID.")
    name: str = Field(description="Organization Name.")
    slug: str = Field(description="URL-friendly handle.")
    type: TenantType = Field(description="Brand or Supplier.")
    location_country: str = Field(description="ISO Country Code.")


class UserRead(SQLModel):
    """
    Standard User Response.
    Includes the 'current_tenant' to help the frontend redirect immediately after login.
    """
    id: UUID
    email: str
    first_name: str
    last_name: str
    is_active: bool

    current_tenant: Optional[ActiveTenantRead] = Field(
        default=None,
        description="The organization the user is currently operating within."
    )


# ==========================================
# Request / Action Models
# ==========================================

class UserSignin(SQLModel):
    """
    Payload for obtaining an access token.
    """
    email: Annotated[EmailStr, StringConstraints(to_lower=True)] = Field(
        description="Registered email address.",
        max_length=255,
        schema_extra={"examples": ["john.doe@example.com"]}
    )
    password: str = Field(
        min_length=8,
        max_length=128,
        description="Plain text password.",
        schema_extra={"examples": ["Str0ngP@ssw0rd!"]}
    )


class UserCreate(SQLModel):
    """
    Payload for New User Registration (Onboarding).

    This handles two flows:
    1. **Direct Signup:** User creates a fresh Tenant (Brand or Supplier).
    2. **Invite Signup:** User registers to fulfill a B2B Connection Request (via `invitation_token`).
    """
    first_name: str = Field(
        min_length=1,
        max_length=50,
        description="User's given name.",
        schema_extra={"examples": ["Jane"]}
    )
    last_name: str = Field(
        min_length=1,
        max_length=50,
        description="User's family name.",
        schema_extra={"examples": ["Doe"]}
    )
    email: Annotated[EmailStr, StringConstraints(to_lower=True)] = Field(
        description="Unique email address for signin.",
        max_length=255,
        schema_extra={"examples": ["jane.doe@supplier.com"]}
    )
    password: str = Field(
        min_length=8,
        max_length=128,
        description="Plain text password.",
        schema_extra={"examples": ["SecurePass123!"]}
    )

    # Organization Details
    company_name: str = Field(
        min_length=2,
        max_length=100,
        description="The legal name of the new organization being created.",
        schema_extra={"examples": ["Acme Textiles Ltd."]}
    )

    location_country: str = Field(
        min_length=2,
        max_length=2,
        description="ISO 3166-1 alpha-2 country code. Critical for supply chain geo-fencing.",
        schema_extra={"examples": ["FR", "CN", "TR"]}
    )

    account_type: RegistrationTenantType = Field(
        description="Whether you are registering as a Brand (Buyer) or Supplier (Seller)."
    )

    # Linkage Logic
    invitation_token: Optional[str] = Field(
        default=None,
        description="If you received an email invite from a Brand, paste the token here. "
                    "This will automatically connect your new account to the Brand's address book.",
        schema_extra={"examples": ["abc-123-token-string"]}
    )
