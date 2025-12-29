from typing import List, Optional
import uuid
from loguru import logger
from sqlmodel import Session, select, or_, col
from fastapi import HTTPException, status

from app.db.schema import User, Tenant, Material
from app.models.material import MaterialCreate, MaterialUpdate, MaterialRead


class MaterialService:
    def __init__(self, session: Session):
        self.session = session

    def _get_tenant_id(self, user: User) -> uuid.UUID:
        tenant_id = getattr(user, "_tenant_id", None)
        if not tenant_id:
            raise HTTPException(
                status_code=403, detail="No active tenant context.")
        return tenant_id

    def list_materials(self, user: User, query: Optional[str] = None) -> List[MaterialRead]:
        """
        Fetch all materials visible to this tenant.
        Includes: Global System Materials + Tenant's Custom Materials.
        """
        tenant_id = self._get_tenant_id(user)

        # Logic: (Tenant IS NULL) OR (Tenant == Current User)
        statement = select(Material).where(
            or_(Material.tenant_id == None, Material.tenant_id == tenant_id)
        )

        if query:
            # Case-insensitive search on Name or Code
            search_fmt = f"%{query}%"
            statement = statement.where(
                or_(
                    col(Material.name).ilike(search_fmt),
                    col(Material.code).ilike(search_fmt)
                )
            )

        # Order by Name
        statement = statement.order_by(Material.name.asc())

        results = self.session.exec(statement).all()

        return [
            MaterialRead(
                id=m.id,
                name=m.name,
                code=m.code,
                material_type=m.material_type,
                is_system=(m.tenant_id is None)
            )
            for m in results
        ]

    def create_material(self, user: User, data: MaterialCreate) -> MaterialRead:
        """
        Create a private custom material for the tenant.
        """
        tenant_id = self._get_tenant_id(user)

        # Check unique code globally (Database constraint)
        existing = self.session.exec(
            select(Material).where(Material.code == data.code)
        ).first()

        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Material code '{data.code}' already exists in the library."
            )

        material = Material(
            tenant_id=tenant_id,  # Link to creator
            name=data.name,
            code=data.code,
            material_type=data.material_type
        )

        try:
            self.session.add(material)
            self.session.commit()
            self.session.refresh(material)

            return MaterialRead(
                id=material.id,
                name=material.name,
                code=material.code,
                material_type=material.material_type,
                is_system=False
            )
        except Exception as e:
            self.session.rollback()
            logger.error(f"Material creation failed: {e}")
            raise HTTPException(
                status_code=500, detail="Could not create material.")

    def update_material(self, user: User, material_id: uuid.UUID, data: MaterialUpdate) -> MaterialRead:
        tenant_id = self._get_tenant_id(user)

        material = self.session.get(Material, material_id)
        if not material:
            raise HTTPException(status_code=404, detail="Material not found.")

        # ACCESS CONTROL: Only allow editing if it belongs to this tenant
        if material.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403,
                detail="You cannot edit System Materials or materials owned by others."
            )

        if data.name:
            material.name = data.name
        if data.material_type:
            material.material_type = data.material_type

        self.session.add(material)
        self.session.commit()
        self.session.refresh(material)

        return MaterialRead(
            id=material.id,
            name=material.name,
            code=material.code,
            material_type=material.material_type,
            is_system=False
        )

    def delete_material(self, user: User, material_id: uuid.UUID):
        tenant_id = self._get_tenant_id(user)

        material = self.session.get(Material, material_id)
        if not material:
            raise HTTPException(status_code=404, detail="Material not found.")

        # ACCESS CONTROL
        if material.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403,
                detail="You cannot delete System Materials."
            )

        # Check for usage (Foreign Key Constraint protection)
        # Ideally, check if used in any ProductVersions before deleting
        # But SQLModel/SQLAlchemy will likely throw IntegrityError if we don't.
        # For better UX, we can pre-check:
        # used_in_bom = session.exec(select(VersionMaterial).where(material_id=id)).first()
        # if used_in_bom: raise 400 "Cannot delete material used in products."

        try:
            self.session.delete(material)
            self.session.commit()
            return {"message": "Material deleted successfully."}
        except Exception as e:
            self.session.rollback()
            # Likely IntegrityError if used in a BOM
            raise HTTPException(
                status_code=400,
                detail="Cannot delete this material because it is currently used in one or more products."
            )
