from enum import Enum
from typing import Optional
from uuid import UUID
from sqlmodel import SQLModel, Field
from pydantic import EmailStr, StringConstraints
from typing_extensions import Annotated

from app.db.schema import TenantType


class RegistrationTenantType(str, Enum):
    BRAND = TenantType.BRAND.value
    SUPPLIER = TenantType.SUPPLIER.value


class ActiveTenantRead(SQLModel):
    id: UUID
    name: str
    slug: str
    type: TenantType
    location_country: str


class UserRead(SQLModel):
    id: UUID
    email: str
    first_name: str
    last_name: str
    is_active: bool
    current_tenant: Optional[ActiveTenantRead] = None


class UserSignin(SQLModel):
    email: Annotated[EmailStr, StringConstraints(to_lower=True)] = Field(
        description="Registered email address of the user.",
        max_length=255
    )
    password: str = Field(
        min_length=8,
        max_length=128,
        description="Plain text password."
    )


class UserCreate(SQLModel):
    """
    DTO for User Registration.
    Now includes fields to establish the initial Organization (Brand/Supplier/Hybrid).
    """
    first_name: str = Field(
        min_length=1,
        max_length=50,
        description="User's given name."
    )
    last_name: str = Field(
        min_length=1,
        max_length=50,
        description="User's family name."
    )
    email: Annotated[EmailStr, StringConstraints(to_lower=True)] = Field(
        description="Unique email address for signin.",
        max_length=255
    )
    password: str = Field(
        min_length=8,
        max_length=128,
        description="Plain text password."
    )

    # Organization Details
    company_name: str = Field(min_length=2, max_length=100)

    # Schema requires this for Geo-Fencing logic
    location_country: str = Field(
        min_length=2,
        max_length=2,
        description="ISO 2-letter country code (e.g. US, FR)"
    )
    account_type: RegistrationTenantType
