# app/services/material.py
import uuid
from typing import List, Optional
from sqlmodel import Session, select, or_, col
from fastapi import HTTPException
from loguru import logger

from app.db.schema import User, Tenant, TenantType, MaterialDefinition
from app.models.material_definition import (
    MaterialDefinitionCreate,
    MaterialDefinitionUpdate,
    MaterialDefinitionRead
)


class MaterialDefinitionService:
    def __init__(self, session: Session):
        self.session = session

    def _get_supplier_context(self, user: User) -> uuid.UUID:
        """
        Helper: 
        1. Retrieves the active tenant ID.
        2. Verifies the Tenant exists.
        3. STRICTLY ENFORCES that the Tenant is a SUPPLIER.
        """
        # Assumes your auth middleware sets _tenant_id on the user object
        tenant_id = getattr(user, "_tenant_id", None)

        if not tenant_id:
            raise HTTPException(
                status_code=403, detail="No active tenant context.")

        # Check Tenant Type in DB
        tenant = self.session.get(Tenant, tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        # ENFORCEMENT: Brands/Admins cannot manage this library
        if tenant.type != TenantType.SUPPLIER:
            raise HTTPException(
                status_code=403,
                detail="Access Forbidden. Only Suppliers can manage Material Libraries."
            )

        return tenant_id

    def list_materials(self, user: User, query: Optional[str] = None) -> List[MaterialDefinitionRead]:
        """
        Supplier only: View System Materials + My Private Materials.
        """
        tenant_id = self._get_supplier_context(user)

        # Logic: (Tenant IS NULL [System]) OR (Tenant == Current Supplier)
        statement = select(MaterialDefinition).where(
            or_(MaterialDefinition.tenant_id == None,
                MaterialDefinition.tenant_id == tenant_id)
        )

        if query:
            search_fmt = f"%{query}%"
            statement = statement.where(
                or_(
                    col(MaterialDefinition.name).ilike(search_fmt),
                    col(MaterialDefinition.code).ilike(search_fmt)
                )
            )

        statement = statement.order_by(MaterialDefinition.name.asc())
        results = self.session.exec(statement).all()

        return [
            MaterialDefinitionRead(
                id=m.id,
                name=m.name,
                code=m.code,
                description=m.description,
                material_type=m.material_type,
                default_carbon_footprint=m.default_carbon_footprint,
                is_system=(m.tenant_id is None)
            )
            for m in results
        ]

    def create_material(self, user: User, data: MaterialDefinitionCreate) -> MaterialDefinitionRead:
        """
        Supplier only: Create private material.
        """
        tenant_id = self._get_supplier_context(user)

        # Check unique code globally to prevent confusion
        existing = self.session.exec(
            select(MaterialDefinition).where(
                MaterialDefinition.code == data.code)
        ).first()

        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Material code '{data.code}' already exists in the library."
            )

        material = MaterialDefinition(
            tenant_id=tenant_id,
            name=data.name,
            code=data.code,
            description=data.description,
            material_type=data.material_type,
            default_carbon_footprint=data.default_carbon_footprint
        )

        try:
            self.session.add(material)
            self.session.commit()
            self.session.refresh(material)

            return MaterialDefinitionRead(
                id=material.id,
                name=material.name,
                code=material.code,
                description=material.description,
                material_type=material.material_type,
                default_carbon_footprint=material.default_carbon_footprint,
                is_system=False
            )
        except Exception as e:
            self.session.rollback()
            logger.error(f"Material creation failed: {e}")
            raise HTTPException(
                status_code=500, detail="Could not create material.")

    def update_material(self, user: User, material_id: uuid.UUID, data: MaterialDefinitionUpdate) -> MaterialDefinitionRead:
        """
        Supplier only: Update OWN material.
        """
        tenant_id = self._get_supplier_context(user)

        material = self.session.get(MaterialDefinition, material_id)
        if not material:
            raise HTTPException(status_code=404, detail="Material not found.")

        # STRICT OWNERSHIP CHECK
        if material.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403,
                detail="You cannot edit System Materials or materials owned by other suppliers."
            )

        if data.name:
            material.name = data.name
        if data.description is not None:
            material.description = data.description
        if data.material_type:
            material.material_type = data.material_type
        if data.default_carbon_footprint is not None:
            material.default_carbon_footprint = data.default_carbon_footprint

        self.session.add(material)
        self.session.commit()
        self.session.refresh(material)

        return MaterialDefinitionRead(
            id=material.id,
            name=material.name,
            code=material.code,
            description=material.description,
            material_type=material.material_type,
            default_carbon_footprint=material.default_carbon_footprint,
            is_system=False
        )

    def delete_material(self, user: User, material_id: uuid.UUID):
        """
        Supplier only: Delete OWN material.
        """
        tenant_id = self._get_supplier_context(user)

        material = self.session.get(MaterialDefinition, material_id)
        if not material:
            raise HTTPException(status_code=404, detail="Material not found.")

        # STRICT OWNERSHIP CHECK
        if material.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403,
                detail="You cannot delete System Materials or materials owned by other suppliers."
            )

        try:
            self.session.delete(material)
            self.session.commit()
            return {"message": "Material deleted successfully."}
        except Exception as e:
            self.session.rollback()
            # This happens if the material is linked to a ProductVersionMaterial
            raise HTTPException(
                status_code=400,
                detail="Cannot delete this material because it is currently used in a product batch."
            )
