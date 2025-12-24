from uuid import UUID
from sqlmodel import SQLModel, Field
from pydantic import EmailStr, StringConstraints
from typing_extensions import Annotated
from app.db.schema import TenantType


class UserRead(SQLModel):
    id: UUID
    email: str
    first_name: str
    last_name: str
    is_active: bool


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

    # New Fields for Onboarding Flow
    company_name: str = Field(
        min_length=2,
        max_length=100,
        description="The legal name of the Brand or Supplier organization."
    )
    location_country: str = Field(min_length=2, max_length=2)
    account_type: TenantType = Field(
        description="The type of account to create: 'brand', 'supplier', or 'hybrid'."
    )
