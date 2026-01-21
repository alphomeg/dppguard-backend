from uuid import UUID
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class DashboardStats(SQLModel):
    """
    High-level KPIs for the Supplier Dashboard Home.
    Used to render the top-level counters/badges.
    """
    pending_invites: int = Field(
        description="Number of Brands waiting for a connection acceptance.",
        schema_extra={"example": 3}
    )
    active_tasks: int = Field(
        description="Number of open Product Data Requests (Sent, In Progress, or Changes Requested).",
        schema_extra={"example": 12}
    )
    completed_tasks: int = Field(
        description="Total number of Product Data Requests successfully submitted and approved.",
        schema_extra={"example": 150}
    )
    connected_brands: int = Field(
        description="Number of active B2B relationships with Brands.",
        schema_extra={"example": 8}
    )


class ConnectionRequestItem(SQLModel):
    """
    Represents an incoming B2B handshake request from a Brand.
    Displayed in the 'New Partner Requests' widget.
    """
    id: UUID = Field(
        description="The unique ID of the TenantConnection record. Used to accept/decline."
    )
    brand_name: str = Field(
        description="Display name of the requesting Brand.",
        schema_extra={"example": "Acme Fashion Group"}
    )
    brand_handle: str = Field(
        description="Unique platform slug of the Brand.",
        schema_extra={"example": "acme-fashion"}
    )
    invited_at: datetime = Field(
        description="Timestamp when the invitation was sent."
    )
    note: Optional[str] = Field(
        default=None,
        description="Personal message from the Brand regarding the connection.",
        schema_extra={
            "example": "We would like to onboard you for the Fall 2025 collection."}
    )
