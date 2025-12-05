from uuid import UUID
from sqlmodel import SQLModel, Field
from pydantic import EmailStr, StringConstraints
from typing_extensions import Annotated


class UserRead(SQLModel):
    id: UUID
    email: str
    first_name: str
    last_name: str
    is_active: bool


class UserSignin(SQLModel):
    """
    Data Transfer Object (DTO) for User Signin.
    This model validates input before it touches the authentication logic.
    """

    email: Annotated[EmailStr, StringConstraints(to_lower=True)] = Field(
        description="Registered email address of the user.",
        max_length=255  # Standard DB limit for emails
    )

    password: str = Field(
        min_length=8,
        max_length=128,  # Prevent denial of service via long password hashing
        description="Plain text password."
    )


class UserCreate(SQLModel):
    """
    Data Transfer Object (DTO) for User Registration.
    This model validates input before it touches the database or service layer.
    """

    first_name: str = Field(
        min_length=1,
        max_length=50,
        description="User's given name. Must be between 1 and 50 characters."
    )

    last_name: str = Field(
        min_length=1,
        max_length=50,
        description="User's family name. Must be between 1 and 50 characters."
    )

    # EmailStr automatically validates format (e.g., user@domain.com)
    email: Annotated[EmailStr, StringConstraints(to_lower=True)] = Field(
        description="Unique email address for signin.",
        max_length=255  # Standard DB limit for emails
    )

    password: str = Field(
        min_length=8,
        max_length=128,  # Prevent denial of service via long password hashing
        description="Plain text password. Must be at least 8 characters."
    )
