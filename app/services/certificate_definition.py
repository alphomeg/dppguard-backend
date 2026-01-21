import uuid
from typing import List, Optional
from loguru import logger
from sqlmodel import Session, select, or_, col, update
from fastapi import HTTPException, BackgroundTasks

from app.db.schema import (
    User, Tenant, TenantType, CertificateDefinition,
    CertificateCategory, AuditAction, ProductVersionCertificate
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

    def _check_uniqueness(self, tenant_id: uuid.UUID, name: Optional[str], code: Optional[str], exclude_id: Optional[uuid.UUID] = None):
        """
        Enforces uniqueness for Name and Code.
        Scope: 
        1. The Tenant's own library.
        2. The System Global library (tenant_id is None).

        You cannot create a certificate named "GOTS" if "GOTS" already exists in the System.
        """
        # Base Query: Look in System Global OR Current Tenant
        statement = select(CertificateDefinition).where(
            or_(
                CertificateDefinition.tenant_id == tenant_id,
                CertificateDefinition.tenant_id == None
            )
        )

        # Filter: Match Name OR Code
        conditions = []
        if name:
            conditions.append(CertificateDefinition.name == name)
        if code:
            conditions.append(CertificateDefinition.code == code)

        if not conditions:
            return

        statement = statement.where(or_(*conditions))

        # Exclude current record (for Updates)
        if exclude_id:
            statement = statement.where(CertificateDefinition.id != exclude_id)

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

    def list_definitions(self, user: User, query: Optional[str] = None, category: Optional[CertificateCategory] = None) -> List[CertificateDefinitionRead]:
        """
        View Certificates.
        Visibility: System Global Records + Records created by this Tenant.
        """
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

        statement = statement.order_by(CertificateDefinition.updated_at.desc())
        results = self.session.exec(statement).all()

        return [
            CertificateDefinitionRead(
                id=c.id,
                name=c.name,
                code=c.code,
                issuer_authority=c.issuer_authority,
                category=c.category,
                description=c.description,
                created_at=c.created_at,
                updated_at=c.updated_at,
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
        """
        Create private certificate (Supplier).
        """
        tenant = self._get_supplier_context(user)

        # Check Uniqueness (Name AND Code against Tenant AND System)
        self._check_uniqueness(tenant.id, data.name, data.code)

        definition = CertificateDefinition(
            tenant_id=tenant.id,
            name=data.name,
            code=data.code,
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
                code=definition.code,
                issuer_authority=definition.issuer_authority,
                category=definition.category,
                description=definition.description,
                created_at=definition.created_at,
                updated_at=definition.updated_at,
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
        """
        Update OWN certificate.
        """
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

        # Check Uniqueness only if fields are changing
        # We pass values only if they are not None, to check for conflicts
        check_name = data.name if data.name != definition.name else None
        check_code = data.code if data.code != definition.code else None

        if check_name or check_code:
            self._check_uniqueness(
                tenant.id,
                check_name if check_name else None,
                check_code if check_code else None,
                exclude_id=definition.id
            )

        # Apply Updates
        if data.name:
            definition.name = data.name
        if data.code:
            definition.code = data.code
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
            code=definition.code,
            issuer_authority=definition.issuer_authority,
            category=definition.category,
            description=definition.description,
            created_at=definition.created_at,
            updated_at=definition.updated_at,
            is_system=False
        )

    def delete_definition(
        self,
        user: User,
        def_id: uuid.UUID,
        background_tasks: BackgroundTasks
    ):
        """
        Delete OWN certificate.

        This explicitly unlinks any ProductVersionCertificate that reference this certificate
        and logs exactly which versions were affected.
        """
        tenant = self._get_supplier_context(user)

        definition = self.session.get(CertificateDefinition, def_id)
        if not definition:
            raise HTTPException(
                status_code=404, detail="Certificate definition not found.")

        if definition.tenant_id != tenant.id:
            raise HTTPException(
                status_code=403, detail="You cannot delete System Definitions.")

        snapshot_name = definition.name
        snapshot_code = definition.code

        try:
            # 1. Identify which records will be affected (for the Audit Log)
            # We select just the ID (and optionally version_id) to keep it lightweight
            affected_records_stmt = select(ProductVersionCertificate.id).where(
                ProductVersionCertificate.certificate_type_id == def_id
            )
            # exec().all() returns a list of UUIDs because we selected a single column
            affected_pvm_ids = self.session.exec(affected_records_stmt).all()

            # Convert UUIDs to strings for JSON serialization in the audit log
            affected_pvm_ids_str = [str(pid) for pid in affected_pvm_ids]

            # 2. Unlink the material (Set FK to NULL)
            if affected_pvm_ids:
                unlink_statement = (
                    update(ProductVersionCertificate)
                    .where(col(ProductVersionCertificate.id).in_(affected_pvm_ids))
                    .values(certificate_type_id=None)
                )
                self.session.exec(unlink_statement)

            # 3. Delete the definition
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
                changes={
                    "name": snapshot_name,
                    "code": snapshot_code,
                    "unlinked_product_version_certificate_ids": affected_pvm_ids_str,
                    "unlinked_count": len(affected_pvm_ids_str)
                }
            )

            return {"message": "Certificate definition deleted successfully."}
        except Exception as e:
            self.session.rollback()
            raise HTTPException(
                status_code=400,
                detail="Cannot delete this definition because it is currently used by product versions."
            )
