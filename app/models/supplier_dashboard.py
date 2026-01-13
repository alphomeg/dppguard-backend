from uuid import UUID
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel


class DashboardStats(SQLModel):
    pending_invites: int
    active_tasks: int
    completed_tasks: int
    connected_brands: int


class ConnectionRequestItem(SQLModel):
    id: UUID
    brand_name: str
    brand_handle: str
    invited_at: datetime
    note: Optional[str] = None


class ProductTaskItem(SQLModel):
    id: UUID
    product_name: str
    version_name: str
    sku: Optional[str]
    brand_name: str
    status: str
    completion_percent: int
    due_date: datetime
    created_at: datetime
