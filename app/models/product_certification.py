from uuid import UUID
from datetime import date
from typing import Optional
from sqlmodel import SQLModel, Field


class ProductCertificationLinkCreate(SQLModel):
    """
    Payload for linking a certification to a product.
    """
    certification_id: UUID
    certificate_number: str = Field(
        min_length=1, description="License or Certificate ID.")
    valid_until: Optional[date] = None
    digital_document_url: Optional[str] = None


class ProductCertificationLinkRead(ProductCertificationLinkCreate):
    """
    Read model enriched with Certification Reference data.
    """
    certification_name: str
    issuer: str
