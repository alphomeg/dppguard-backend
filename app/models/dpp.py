from typing import List, Optional
from datetime import datetime
from uuid import UUID
from sqlmodel import SQLModel
from app.db.schema import DPPStatus, DPPEventType


class DPPEventBase(SQLModel):
    event_type: DPPEventType
    description: Optional[str] = None
    location: Optional[str] = None


class DPPEventCreate(DPPEventBase):
    pass


class DPPEventRead(DPPEventBase):
    id: UUID
    timestamp: datetime
    actor_id: Optional[UUID] = None


class DPPExtraDetailBase(SQLModel):
    key: str
    value: str
    is_public: bool = True
    display_order: int = 0


class DPPExtraDetailCreate(DPPExtraDetailBase):
    pass


class DPPExtraDetailRead(DPPExtraDetailBase):
    id: UUID


class DPPBase(SQLModel):
    status: DPPStatus = DPPStatus.DRAFT
    target_url: str
    public_uid: Optional[str] = None


class DPPCreate(DPPBase):
    product_id: UUID


class DPPUpdate(SQLModel):
    status: Optional[DPPStatus] = None
    target_url: Optional[str] = None
    qr_code_url: Optional[str] = None
    version: Optional[int] = None


class DPPRead(DPPBase):
    """Basic Passport View"""
    id: UUID
    product_id: UUID
    public_uid: str
    qr_code_url: Optional[str] = None
    version: int
    created_at: datetime
    updated_at: datetime


class DPPFullDetailsRead(DPPRead):
    """
    The Full Digital Twin View.
    Includes the audit log (events) and custom attributes (extra details).
    """
    events: List[DPPEventRead] = []
    extra_details: List[DPPExtraDetailRead] = []
