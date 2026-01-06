from typing import Optional
from uuid import UUID
from sqlmodel import SQLModel, Field


class CertificationCreate(SQLModel):
    """
    Payload for creating a certification.
    """
    name: str = Field(min_length=2, max_length=150,
                      description="Certification Name")
    code: str = Field(min_length=2, max_length=50,
                      description="Unique Code (e.g. CERT-001)")
    issuer: str = Field(min_length=2, max_length=150,
                        description="Issuer / Governing Body")

    # NEW FIELD
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Notes about validity, scope, or renewal."
    )


class CertificationUpdate(SQLModel):
    """
    Payload for updating a custom certification.
    """
    name: Optional[str] = Field(default=None, min_length=2, max_length=150)
    issuer: Optional[str] = Field(default=None, min_length=2, max_length=150)

    # NEW FIELD
    description: Optional[str] = Field(default=None, max_length=500)


class CertificationRead(SQLModel):
    """
    Response model.
    """
    id: UUID
    name: str
    code: str
    issuer: str

    # NEW FIELD
    description: Optional[str]

    is_system: bool = Field(
        description="If True, this is a global standard and cannot be edited.")
