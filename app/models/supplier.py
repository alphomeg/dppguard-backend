from uuid import UUID
from sqlmodel import SQLModel, Field
from typing_extensions import Optional


class SupplierBase(SQLModel):
    name: str = Field(min_length=1, max_length=150)
    location_country: str = Field(min_length=2, max_length=100)
    facility_address: Optional[str] = None
    social_audit_rating: Optional[str] = None


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(SQLModel):
    name: Optional[str] = None
    location_country: Optional[str] = None
    facility_address: Optional[str] = None
    social_audit_rating: Optional[str] = None


class SupplierRead(SupplierBase):
    id: UUID
    tenant_id: UUID
