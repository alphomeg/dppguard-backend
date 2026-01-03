from typing import List, Optional
from sqlmodel import SQLModel
from app.models.version_material import VersionMaterialCreate
from app.models.version_certification import VersionCertificationCreate
from app.models.version_supplier import VersionSupplierCreate


class VersionDataUpdate(SQLModel):
    """
    Full payload for Supplier to save their work.
    """
    # 1. Scalar Environmental Data
    manufacturing_country: Optional[str] = None
    total_carbon_footprint_kg: Optional[float] = None
    total_water_usage_liters: Optional[float] = None
    total_energy_mj: Optional[float] = None
    recycling_instructions: Optional[str] = None
    recyclability_class: Optional[str] = None

    # 2. Bill of Materials
    materials: List[VersionMaterialCreate] = []

    # 3. Supply Chain Map (Tier 2, 3, etc.)
    suppliers: List[VersionSupplierCreate] = []

    # 4. Certificates / Compliance
    certifications: List[VersionCertificationCreate] = []
