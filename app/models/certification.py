from uuid import UUID
from sqlmodel import SQLModel, Field
from typing import Optional


class CertificationBase(SQLModel):
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=50)
    issuer: str = Field(min_length=1, max_length=100)


class CertificationCreate(CertificationBase):
    """
    Payload for creating a new certification.
    Inherits all fields from Base as required.
    """
    pass


class CertificationUpdate(SQLModel):
    """
    Payload for updating an existing certification.
    All fields are optional to allow partial updates (PATCH).
    """
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    issuer: Optional[str] = Field(default=None, min_length=1, max_length=100)


class CertificationRead(CertificationBase):
    """
    Response model for reading certification details.
    """
    id: UUID
    tenant_id: Optional[UUID] = None  # Null if it's a system certification
