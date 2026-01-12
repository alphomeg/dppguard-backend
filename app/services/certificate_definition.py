import uuid
from typing import List, Optional
from loguru import logger
from sqlmodel import Session, select, or_, col
from fastapi import HTTPException, BackgroundTasks

from app.db.schema import (
    User, Tenant, TenantType, CertificateDefinition,
    CertificateCategory, AuditAction
)
from app.models.certificate_definition import (
    CertificateDefinitionCreate,
    CertificateDefinitionUpdate,
    CertificateDefinitionRead
)
from app.core.audit import _perform_audit_log


class CertificateDefinitionService:
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
        Write Helper: STRICTLY ENFORCES that the Tenant is a SUPPLIER or ADMIN.
        Brands cannot create or edit definitions.
        """
        tenant = self._get_active_tenant(user)

        if tenant.type != TenantType.SUPPLIER and tenant.type != TenantType.SYSTEM_ADMIN:
            raise HTTPException(
                status_code=403,
                detail="Access Forbidden. Only Suppliers can manage Certificate Definitions."
            )
        return tenant

    def _check_uniqueness(self, tenant_id: uuid.UUID, name: str, exclude_id: Optional[uuid.UUID] = None):
        """
        Enforces uniqueness for Name.
        Scope: 
        1. The Tenant's own library.
        2. The System Global library (tenant_id is None).

        Prevents creating a custom 'GOTS' if System 'GOTS' exists.
        """
        statement = select(CertificateDefinition).where(
            or_(
                CertificateDefinition.tenant_id == tenant_id,  # My Private
                CertificateDefinition.tenant_id == None       # System Global
            )
        ).where(
            CertificateDefinition.name == name
        )

        if exclude_id:
            statement = statement.where(CertificateDefinition.id != exclude_id)

        existing = self.session.exec(statement).first()

        if existing:
            owner = "System Global Library" if existing.tenant_id is None else "Your Custom Library"
            raise HTTPException(
                status_code=409,
                detail=f"Conflict: The certificate name '{name}' already exists in {owner}."
            )

    # ==========================================================================
    # READ OPERATIONS
    # ==========================================================================

    def list_definitions(self, user: User, query: Optional[str] = None, category: Optional[CertificateCategory] = None) -> List[CertificateDefinitionRead]:
        tenant = self._get_active_tenant(user)

        statement = select(CertificateDefinition).where(
            or_(
                CertificateDefinition.tenant_id == None,       # System Global
                CertificateDefinition.tenant_id == tenant.id   # Custom Private
            )
        )

        if query:
            search_fmt = f"%{query}%"
            statement = statement.where(
                or_(
                    col(CertificateDefinition.name).ilike(search_fmt),
                    col(CertificateDefinition.issuer_authority).ilike(search_fmt)
                )
            )

        if category:
            statement = statement.where(
                CertificateDefinition.category == category)

        statement = statement.order_by(CertificateDefinition.name.asc())
        results = self.session.exec(statement).all()

        return [
            CertificateDefinitionRead(
                id=c.id,
                name=c.name,
                issuer_authority=c.issuer_authority,
                category=c.category,
                description=c.description,
                is_system=(c.tenant_id is None)
            )
            for c in results
        ]

    # ==========================================================================
    # WRITE OPERATIONS
    # ==========================================================================

    def create_definition(
        self,
        user: User,
        data: CertificateDefinitionCreate,
        background_tasks: BackgroundTasks
    ) -> CertificateDefinitionRead:

        tenant = self._get_supplier_context(user)

        # UPDATED: Check Name Uniqueness against Tenant AND System
        self._check_uniqueness(tenant.id, data.name)

        definition = CertificateDefinition(
            tenant_id=tenant.id,
            name=data.name,
            issuer_authority=data.issuer_authority,
            category=data.category,
            description=data.description
        )

        try:
            self.session.add(definition)
            self.session.commit()
            self.session.refresh(definition)

            # Audit Log
            background_tasks.add_task(
                _perform_audit_log,
                tenant_id=tenant.id,
                user_id=user.id,
                entity_type="CertificateDefinition",
                entity_id=definition.id,
                action=AuditAction.CREATE,
                changes=data.model_dump(mode='json'),
                ip_address=None
            )

            return CertificateDefinitionRead(
                id=definition.id,
                name=definition.name,
                issuer_authority=definition.issuer_authority,
                category=definition.category,
                description=definition.description,
                is_system=False
            )
        except HTTPException:
            raise
        except Exception as e:
            self.session.rollback()
            logger.error(f"Certificate Definition creation failed: {e}")
            raise HTTPException(
                status_code=500, detail="Could not create definition.")

    def update_definition(
        self,
        user: User,
        def_id: uuid.UUID,
        data: CertificateDefinitionUpdate,
        background_tasks: BackgroundTasks
    ) -> CertificateDefinitionRead:

        tenant = self._get_supplier_context(user)
        definition = self.session.get(CertificateDefinition, def_id)

        if not definition:
            raise HTTPException(
                status_code=404, detail="Certificate definition not found.")

        # STRICT OWNERSHIP CHECK
        if definition.tenant_id != tenant.id:
            raise HTTPException(
                status_code=403,
                detail="You cannot edit System Definitions or definitions owned by other tenants."
            )

        old_state = definition.model_dump()

        # UPDATED: Check uniqueness if name changes
        if data.name is not None and data.name != definition.name:
            self._check_uniqueness(tenant.id, data.name,
                                   exclude_id=definition.id)

        # Apply Updates
        if data.name:
            definition.name = data.name
        if data.issuer_authority:
            definition.issuer_authority = data.issuer_authority
        if data.category:
            definition.category = data.category
        if data.description is not None:
            definition.description = data.description

        self.session.add(definition)
        self.session.commit()
        self.session.refresh(definition)

        # Audit Log
        changes = {k: {"old": old_state.get(k), "new": v} for k, v in data.model_dump(
            exclude_unset=True).items()}

        background_tasks.add_task(
            _perform_audit_log,
            tenant_id=tenant.id,
            user_id=user.id,
            entity_type="CertificateDefinition",
            entity_id=definition.id,
            action=AuditAction.UPDATE,
            changes=changes
        )

        return CertificateDefinitionRead(
            id=definition.id,
            name=definition.name,
            issuer_authority=definition.issuer_authority,
            category=definition.category,
            description=definition.description,
            is_system=False
        )

    def delete_definition(
        self,
        user: User,
        def_id: uuid.UUID,
        background_tasks: BackgroundTasks
    ):
        tenant = self._get_supplier_context(user)
        definition = self.session.get(CertificateDefinition, def_id)

        if not definition:
            raise HTTPException(
                status_code=404, detail="Certificate definition not found.")

        if definition.tenant_id != tenant.id:
            raise HTTPException(
                status_code=403, detail="You cannot delete System Definitions.")

        snapshot_name = definition.name

        try:
            self.session.delete(definition)
            self.session.commit()

            # Audit Log
            background_tasks.add_task(
                _perform_audit_log,
                tenant_id=tenant.id,
                user_id=user.id,
                entity_type="CertificateDefinition",
                entity_id=def_id,
                action=AuditAction.DELETE,
                changes={"name": snapshot_name}
            )

            return {"message": "Certificate definition deleted successfully."}
        except Exception as e:
            self.session.rollback()
            raise HTTPException(
                status_code=400,
                detail="Cannot delete this definition because it is currently used by product versions."
            )
