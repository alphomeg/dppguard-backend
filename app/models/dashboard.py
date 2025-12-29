from typing import Optional
from uuid import UUID
from datetime import datetime
from sqlmodel import SQLModel
from app.db.schema import RequestStatus


class DashboardStats(SQLModel):
    """KPIs for the top of the dashboard"""
    pending_invites: int
    active_tasks: int
    completed_tasks: int
    connected_brands: int


class ConnectionRequestItem(SQLModel):
    """For the 'Connection Requests' list"""
    id: UUID
    brand_name: str
    brand_handle: str
    invited_at: datetime
    note: Optional[str] = None


class ProductTaskItem(SQLModel):
    """For the 'Product Assignments' DataGrid"""
    id: UUID                    # Request ID
    product_name: str
    sku: str
    brand_name: str
    status: RequestStatus
    completion_percent: int
    due_date: Optional[datetime] = None
    created_at: datetime
