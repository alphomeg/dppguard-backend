from typing import Optional
from uuid import UUID
from datetime import date
from sqlmodel import SQLModel, Field


class VersionCertificationCreate(SQLModel):
    """
    Payload for attaching a specific certificate/proof to this version.
    """
    certification_id: UUID = Field(
        description="Link to the standard Certification Type.")
    document_url: str = Field(description="URL to the uploaded file.")
    valid_until: Optional[date] = None
