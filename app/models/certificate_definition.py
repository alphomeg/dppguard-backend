from typing import Optional
from uuid import UUID
from sqlmodel import SQLModel, Field
from app.db.schema import CertificateCategory


class CertificateDefinitionCreate(SQLModel):
    """
    Payload for creating a new Certificate Definition.
    Used by Suppliers to define internal or niche standards not present in the System.
    """
    name: str = Field(
        min_length=2,
        max_length=150,
        description="The official legal name of the standard or certification. Example: 'Internal Lab Report Q4'."
    )
    issuer_authority: str = Field(
        min_length=2,
        max_length=150,
        description="The governing body or organization that officially owns and manages this standard. Example: 'Acme Testing Labs'."
    )
    category: CertificateCategory = Field(
        description="The high-level legal classification (e.g., Environmental, Social). Used for grouping in reports."
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="A summary of what compliance with this standard entails."
    )


class CertificateDefinitionUpdate(SQLModel):
    """
    Payload for updating a custom Certificate Definition.
    Only allows modification of fields owned by the Supplier.
    """
    name: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=150,
        description="Updated name of the standard."
    )
    issuer_authority: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=150,
        description="Updated issuer authority."
    )
    category: Optional[CertificateCategory] = Field(
        default=None,
        description="Updated classification category."
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Updated description."
    )


class CertificateDefinitionRead(SQLModel):
    """
    Response model for Certificate Definitions.
    Combines System Global standards and Tenant Custom standards.
    """
    id: UUID = Field(description="Unique identifier for this definition.")

    name: str = Field(description="The display name of the certificate.")
    issuer_authority: str = Field(description="The issuing authority.")
    category: CertificateCategory = Field(
        description="The category (e.g., Environmental, Social).")
    description: Optional[str] = Field(
        description="Details about the standard.")

    is_system: bool = Field(
        description="If True, this is a Global Standard (read-only). If False, it is a Custom Standard owned by the current Tenant."
    )
