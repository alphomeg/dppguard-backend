from typing import Optional
from uuid import UUID
from datetime import datetime
from sqlmodel import SQLModel, Field


class AssignmentCreate(SQLModel):
    """
    Payload to create a DataContributionRequest.
    """
    supplier_profile_id: UUID
    due_date: Optional[datetime] = None


class ReviewPayload(SQLModel):
    """
    Payload for the Review action on a Request.
    """
    approve: bool
    comment: Optional[str] = Field(
        default=None, description="Required if approving is false.")
