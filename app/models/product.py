from typing import List, Optional
from datetime import datetime, date
from uuid import UUID
from sqlmodel import SQLModel

from app.models.product_material import ProductMaterialLinkRead
from app.models.product_supplier import ProductSupplierLinkRead
from app.models.product_certification import ProductCertificationLinkRead
from app.models.product_spare_part import SparePartRead
from app.models.product_durability import ProductDurabilityRead
from app.models.product_environmental import ProductEnvironmentalRead


class ProductBase(SQLModel):
    gtin: Optional[str] = None
    batch_number: Optional[str] = None
    name: str
    model_reference: str
    brand_name: str
    manufacturing_country: str
    manufacture_date: Optional[date] = None
    care_instructions: Optional[str] = None
    disposal_instructions: Optional[str] = None


class ProductRead(ProductBase):
    """Basic Product View"""
    id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime


class ProductCreate(ProductBase):
    pass


class ProductUpdate(SQLModel):
    gtin: Optional[str] = None
    batch_number: Optional[str] = None
    name: Optional[str] = None
    model_reference: Optional[str] = None
    brand_name: Optional[str] = None
    manufacturing_country: Optional[str] = None
    manufacture_date: Optional[date] = None
    care_instructions: Optional[str] = None
    disposal_instructions: Optional[str] = None


class ProductFullDetailsRead(ProductRead):
    """
    The Digital Product Passport (DPP) View.
    Aggregates the core product with all its extensions and relationships.
    """
    # 1-to-1 Extensions
    durability: Optional[ProductDurabilityRead] = None
    environmental: Optional[ProductEnvironmentalRead] = None

    # Many-to-Many Relationships (Enriched with names/codes)
    materials: List[ProductMaterialLinkRead] = []
    suppliers: List[ProductSupplierLinkRead] = []
    certifications: List[ProductCertificationLinkRead] = []

    # 1-to-Many Relationships
    spare_parts: List[SparePartRead] = []
