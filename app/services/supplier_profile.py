import uuid
import secrets
from typing import List
from loguru import logger
from sqlmodel import Session, select
from fastapi import HTTPException, BackgroundTasks

from app.core.config import settings
from app.core.audit import _perform_audit_log
from app.db.schema import (
    User, Tenant, TenantType, SupplierProfile,
    TenantConnection, ConnectionStatus, AuditAction,
    RelationshipType
)
from app.models.supplier_profile import (
    SupplierProfileCreate, SupplierProfileRead,
    SupplierProfileUpdate
)


class SupplierProfileService:
    def __init__(self, session: Session):
        self.session = session

    def _get_active_tenant(self, user: User) -> Tenant:
        """
        Base Helper: Retrieves the active tenant for the user.
        """
        tenant_id = getattr(user, "_tenant_id", None)
        if not tenant_id:
            raise HTTPException(
                status_code=403, detail="No active tenant context.")

        tenant = self.session.get(Tenant, tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        return tenant

    def _get_brand_context(self, user: User) -> Tenant:
        """
        Write Helper: Strictly enforces that the tenant is a BRAND.
        Only Brands can manage Address Books (Supplier Profiles).
        """
        tenant = self._get_active_tenant(user)
        if tenant.type != TenantType.BRAND:
            raise HTTPException(
                status_code=403,
                detail="Access Forbidden. Only Brands can manage Supplier Address Books."
            )
        return tenant

    def _check_uniqueness(self, tenant_id: uuid.UUID, name: str, exclude_id: uuid.UUID = None):
        """
        Enforces uniqueness for Supplier Name within the Brand's address book.
        """
        statement = select(SupplierProfile).where(
            SupplierProfile.tenant_id == tenant_id,
            SupplierProfile.name == name
        )
        if exclude_id:
            statement = statement.where(SupplierProfile.id != exclude_id)

        existing = self.session.exec(statement).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Conflict detected: A supplier named '{name}' already exists in your address book."
            )

    # ==========================================================================
    # READ OPERATIONS
    # ==========================================================================

    def list_profiles(self, user: User) -> List[SupplierProfileRead]:
        """
        List all supplier profiles.
        OPTIMIZED: Uses denormalized fields to avoid joining TenantConnection 
        for every single row.
        """
        brand = self._get_brand_context(user)

        profiles = self.session.exec(
            select(SupplierProfile)
            .where(SupplierProfile.tenant_id == brand.id)
            .order_by(SupplierProfile.updated_at.desc())
        ).all()

        results = []
        for p in profiles:
            results.append(self._build_read_response(p))

        return results

    # ==========================================================================
    # WRITE OPERATIONS
    # ==========================================================================

    def add_profile(
        self,
        user: User,
        data: SupplierProfileCreate,
        background_tasks: BackgroundTasks
    ) -> SupplierProfileRead:
        """
        Orchestrates the onboarding of a new Supplier.

        **Execution Flow:**
        1. Validates uniqueness of the display name.
        2. Resolves the target:
           - If `public_handle` is provided, resolves the existing Supplier Tenant.
           - If `invite_email` is provided, prepares an email invitation.
        3. **Creates the Handshake (`TenantConnection`) FIRST**:
           - Sets type to `RelationshipType.SUPPLIER`.
           - Generates a security token.
        4. **Creates the Context (`SupplierProfile`) SECOND**:
           - Links it to the created Connection ID.
           - Populates denormalized fields (Status, Slug) for read performance.
        5. Triggers audit logs and (mock) email notifications.
        """
        brand = self._get_brand_context(user)

        # 1. Uniqueness Check
        self._check_uniqueness(brand.id, data.name)

        # 2. Resolve Target (Platform User vs Email Invite)
        target_tenant_id = None
        target_tenant_slug = None

        # Default status for the Profile's denormalized field
        initial_status = ConnectionStatus.PENDING

        if data.public_handle:
            target_tenant = self.session.exec(
                select(Tenant).where(Tenant.slug == data.public_handle)
            ).first()

            if not target_tenant:
                raise HTTPException(
                    status_code=404, detail=f"Company '@{data.public_handle}' not found in directory.")

            if target_tenant.type != TenantType.SUPPLIER:
                raise HTTPException(
                    status_code=400, detail="Invalid Connection: A Brand can only invite a supplier tenant.")

            target_tenant_id = target_tenant.id
            target_tenant_slug = target_tenant.slug

        try:
            invite_token = secrets.token_urlsafe(32)

            conn = TenantConnection(
                requester_tenant_id=brand.id,
                target_tenant_id=target_tenant_id,  # Can be None if email invite
                type=RelationshipType.SUPPLIER,
                status=initial_status,
                invitation_token=invite_token,
                invitation_email=data.invite_email,  # Standardized field name
                request_note=data.request_note,
                retry_count=0
            )
            self.session.add(conn)
            self.session.flush()  # We need conn.id immediately

            # 3. Create Profile
            profile = SupplierProfile(
                tenant_id=brand.id,
                connection_id=conn.id,

                # CRM Data
                name=data.name,
                description=data.description,
                location_country=data.location_country,
                contact_email=data.contact_email,
                contact_name=data.contact_name,
                is_favorite=data.is_favorite,

                # Denormalization (Populate for performance)
                supplier_tenant_id=target_tenant_id,
                connection_status=initial_status,
                slug=target_tenant_slug,
                retry_count=0,
                invitation_email=data.invite_email,
            )
            self.session.add(profile)
            self.session.commit()
            self.session.refresh(profile)

            # 5. MOCK Notification (In production, use email service)
            if data.invite_email:
                link = f"{settings.public_dashboard_host}/register?token={invite_token}"
                logger.info(f" [EMAIL] Invite {data.invite_email}: {link}")

            # 6. Audit Log
            background_tasks.add_task(
                _perform_audit_log,
                tenant_id=brand.id,
                user_id=user.id,
                entity_type="SupplierProfile",
                entity_id=profile.id,
                action=AuditAction.CREATE,
                changes=data.model_dump(mode='json')
            )

            return self._build_read_response(profile)

        except Exception as e:
            self.session.rollback()
            logger.error(f"Add Supplier Error: {e}")
            raise HTTPException(
                status_code=500, detail="Failed to add supplier.")

    def update_profile(
        self,
        user: User,
        profile_id: uuid.UUID,
        data: SupplierProfileUpdate,
        background_tasks: BackgroundTasks
    ) -> SupplierProfileRead:
        """
        Edit Address Book details (Name, Notes, Favorites).
        Does NOT affect the actual Connection status.
        """
        brand = self._get_brand_context(user)

        profile = self.session.get(SupplierProfile, profile_id)
        if not profile or profile.tenant_id != brand.id:
            raise HTTPException(
                status_code=404, detail="Supplier profile not found.")

        # Snapshot for Audit
        old_state = profile.model_dump()

        # Uniqueness Check if name changes
        if data.name and data.name != profile.name:
            self._check_uniqueness(brand.id, data.name, exclude_id=profile.id)
            profile.name = data.name

        if data.description is not None:
            profile.description = data.description
        if data.contact_name is not None:
            profile.contact_name = data.contact_name
        if data.contact_email is not None:
            profile.contact_email = data.contact_email
        if data.is_favorite is not None:
            profile.is_favorite = data.is_favorite

        self.session.add(profile)
        self.session.commit()
        self.session.refresh(profile)

        # Audit
        changes = {k: {"old": old_state.get(k), "new": v} for k, v in data.model_dump(
            exclude_unset=True).items()}
        background_tasks.add_task(
            _perform_audit_log,
            tenant_id=brand.id,
            user_id=user.id,
            entity_type="SupplierProfile",
            entity_id=profile.id,
            action=AuditAction.UPDATE,
            changes=changes
        )

        return self._build_read_response(profile)

    # ==========================================================================
    # ACTION: DISCONNECT (Soft Delete / Archive)
    # ==========================================================================

    def disconnect_supplier(
        self,
        user: User,
        profile_id: uuid.UUID,
        background_tasks: BackgroundTasks
    ):
        """
        Suspends the business relationship with a supplier.

        **Logic:**
        1. Validates the profile belongs to the requesting Brand.
        2. Updates the Source of Truth: Sets `TenantConnection.status` to `SUSPENDED`.
        3. Updates the View: Syncs `SupplierProfile.connection_status` to `SUSPENDED`.
        4. Invalidates any pending invitation tokens.
        """
        brand = self._get_brand_context(user)

        profile = self.session.get(SupplierProfile, profile_id)
        if not profile or profile.tenant_id != brand.id:
            raise HTTPException(
                status_code=404, detail="Supplier profile not found.")

        conn = profile.connection
        if not conn:
            raise HTTPException(
                status_code=400, detail="No active connection found to disconnect.")

        if conn.status == ConnectionStatus.SUSPENDED:
            raise HTTPException(
                status_code=400, detail="Supplier is already SUSPENDED.")

        # Execute Disconnect
        old_status = conn.status
        new_status = ConnectionStatus.SUSPENDED

        conn.status = new_status
        conn.invitation_token = None  # Invalidate any pending tokens

        profile.connection_status = new_status

        self.session.add(conn)
        self.session.add(profile)
        self.session.commit()

        # Audit
        background_tasks.add_task(
            _perform_audit_log,
            tenant_id=brand.id,
            user_id=user.id,
            entity_type="SupplierProfile",
            entity_id=profile_id,
            action=AuditAction.UPDATE,
            changes={
                "action": "DISCONNECT",
                "old_status": str(old_status),
                "new_status": "SUSPENDED"
            }
        )

        return {"message": "Supplier SUSPENDED successfully. History preserved."}

    # ==========================================================================
    # INTERNAL HELPER
    # ==========================================================================
    def _build_read_response(self, profile: SupplierProfile) -> SupplierProfileRead:
        """
        Helper to construct the Read model.
        OPTIMIZED: Reads purely from SupplierProfile denormalized fields. 
        """
        return SupplierProfileRead(
            id=profile.id,
            name=profile.name,
            description=profile.description,
            location_country=profile.location_country,
            contact_name=profile.contact_name,
            contact_email=profile.contact_email,
            is_favorite=profile.is_favorite,

            # Denormalized fields
            connection_status=profile.connection_status,
            connected_handle=profile.slug,
            retry_count=profile.retry_count,
            audit_invite_email=profile.invitation_email,

            created_at=profile.created_at,
            updated_at=profile.updated_at
        )
