import uuid
from typing import List, Optional
from loguru import logger
from sqlmodel import Session, select, or_, col
from fastapi import HTTPException, BackgroundTasks

from app.db.schema import (
    User, Tenant, TenantType, MaterialDefinition, AuditAction
)
from app.models.material_definition import (
    MaterialDefinitionCreate,
    MaterialDefinitionUpdate,
    MaterialDefinitionRead
)
from app.core.audit import _perform_audit_log


class MaterialDefinitionService:
    def __init__(self, session: Session):
        self.session = session

    def _get_active_tenant(self, user: User) -> Tenant:
        """
        Base Helper: Retrieves the active tenant for the user.
        Used for READ operations (Brands, Suppliers, Admins).
        """
        tenant_id = getattr(user, "_tenant_id", None)
        if not tenant_id:
            raise HTTPException(
                status_code=403, detail="No active tenant context.")

        tenant = self.session.get(Tenant, tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        return tenant

    def _get_supplier_context(self, user: User) -> Tenant:
        """
        Write Helper: Strictly enforces that the tenant is a SUPPLIER or ADMIN.
        Used for WRITE operations.
        """
        tenant = self._get_active_tenant(user)

        if tenant.type != TenantType.SUPPLIER and tenant.type != TenantType.SYSTEM_ADMIN:
            raise HTTPException(
                status_code=403,
                detail="Access Forbidden. Only Suppliers can manage Material Libraries."
            )
        return tenant

    def _check_uniqueness(self, tenant_id: uuid.UUID, name: Optional[str], code: Optional[str], exclude_id: Optional[uuid.UUID] = None):
        """
        Enforces uniqueness for Name and Code.
        Scope: 
        1. The Tenant's own library.
        2. The System Global library (tenant_id is None).

        You cannot create a material named "Cotton" if "Cotton" already exists in the System.
        """
        # Base Query: Look in System Global OR Current Tenant
        statement = select(MaterialDefinition).where(
            or_(
                MaterialDefinition.tenant_id == tenant_id,
                MaterialDefinition.tenant_id == None
            )
        )

        # Filter: Match Name OR Code
        conditions = []
        if name:
            conditions.append(MaterialDefinition.name == name)
        if code:
            conditions.append(MaterialDefinition.code == code)

        if not conditions:
            return

        statement = statement.where(or_(*conditions))

        # Exclude current record (for Updates)
        if exclude_id:
            statement = statement.where(MaterialDefinition.id != exclude_id)

        existing = self.session.exec(statement).first()

        if existing:
            # Determine which field caused the conflict for a better error message
            conflict_field = "Name" if existing.name == name else "Code"
            owner = "System Global" if existing.tenant_id is None else "Your Library"

            raise HTTPException(
                status_code=409,
                detail=f"Conflict detected: The {conflict_field} '{getattr(existing, conflict_field.lower())}' already exists in {owner}."
            )

    # ==========================================================================
    # READ OPERATIONS
    # ==========================================================================

    def list_materials(self, user: User, query: Optional[str] = None) -> List[MaterialDefinitionRead]:
        """
        View Materials.
        Visibility: System Global Records + Records created by this Tenant.
        """
        tenant = self._get_supplier_context(user)

        # Logic: (Tenant IS NULL [System]) OR (Tenant == Current Tenant)
        statement = select(MaterialDefinition).where(
            or_(
                MaterialDefinition.tenant_id == None,
                MaterialDefinition.tenant_id == tenant.id
            )
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

    # ==========================================================================
    # WRITE OPERATIONS
    # ==========================================================================

    def create_material(
        self,
        user: User,
        data: MaterialDefinitionCreate,
        background_tasks: BackgroundTasks
    ) -> MaterialDefinitionRead:
        """
        Create private material (Supplier) or Global material (Admin).
        """
        tenant = self._get_supplier_context(user)

        # Check Uniqueness (Name AND Code against Tenant AND System)
        self._check_uniqueness(tenant.id, data.name, data.code)

        material = MaterialDefinition(
            tenant_id=tenant.id,
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

            # Audit Log
            background_tasks.add_task(
                _perform_audit_log,
                tenant_id=tenant.id,
                user_id=user.id,
                entity_type="MaterialDefinition",
                entity_id=material.id,
                action=AuditAction.CREATE,
                changes=data.model_dump(mode='json'),
                ip_address=None
            )

            return MaterialDefinitionRead(
                id=material.id,
                name=material.name,
                code=material.code,
                description=material.description,
                material_type=material.material_type,
                default_carbon_footprint=material.default_carbon_footprint,
                is_system=False
            )
        except HTTPException:
            raise
        except Exception as e:
            self.session.rollback()
            logger.error(f"Material creation failed: {e}")
            raise HTTPException(
                status_code=500, detail="Could not create material.")

    def update_material(
        self,
        user: User,
        material_id: uuid.UUID,
        data: MaterialDefinitionUpdate,
        background_tasks: BackgroundTasks
    ) -> MaterialDefinitionRead:
        """
        Update OWN material.
        """
        tenant = self._get_supplier_context(user)

        material = self.session.get(MaterialDefinition, material_id)
        if not material:
            raise HTTPException(status_code=404, detail="Material not found.")

        # STRICT OWNERSHIP CHECK
        if material.tenant_id != tenant.id:
            raise HTTPException(
                status_code=403,
                detail="You cannot edit System Materials or materials owned by other tenants."
            )

        # Snapshot for audit
        old_state = material.model_dump()

        # Check Uniqueness only if fields are changing
        # We pass values only if they are not None, to check for conflicts
        check_name = data.name if data.name != material.name else None

        if check_name:
            self._check_uniqueness(tenant.id, check_name,
                                   None, exclude_id=material.id)

        # Apply Updates
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

        # Audit Log
        changes = {k: {"old": old_state.get(k), "new": v} for k, v in data.model_dump(
            exclude_unset=True).items()}

        background_tasks.add_task(
            _perform_audit_log,
            tenant_id=tenant.id,
            user_id=user.id,
            entity_type="MaterialDefinition",
            entity_id=material.id,
            action=AuditAction.UPDATE,
            changes=changes
        )

        return MaterialDefinitionRead(
            id=material.id,
            name=material.name,
            code=material.code,
            description=material.description,
            material_type=material.material_type,
            default_carbon_footprint=material.default_carbon_footprint,
            is_system=False
        )

    def delete_material(
        self,
        user: User,
        material_id: uuid.UUID,
        background_tasks: BackgroundTasks
    ):
        """
        Delete OWN material.
        """
        tenant = self._get_supplier_context(user)

        material = self.session.get(MaterialDefinition, material_id)
        if not material:
            raise HTTPException(status_code=404, detail="Material not found.")

        # STRICT OWNERSHIP CHECK
        if material.tenant_id != tenant.id:
            raise HTTPException(
                status_code=403,
                detail="You cannot delete System Materials or materials owned by other suppliers."
            )

        snapshot_name = material.name

        try:
            self.session.delete(material)
            self.session.commit()

            # Audit Log
            background_tasks.add_task(
                _perform_audit_log,
                tenant_id=tenant.id,
                user_id=user.id,
                entity_type="MaterialDefinition",
                entity_id=material_id,
                action=AuditAction.DELETE,
                changes={"name": snapshot_name, "code": material.code}
            )

            return {"message": "Material deleted successfully."}
        except Exception as e:
            self.session.rollback()
            # This happens if the material is linked to a ProductVersionMaterial
            raise HTTPException(
                status_code=400,
                detail="Cannot delete this material because it is currently used in a product batch."
            )
