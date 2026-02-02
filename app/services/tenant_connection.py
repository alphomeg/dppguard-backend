import uuid
import secrets
from typing import List
from sqlmodel import Session, select, or_, col
from fastapi import HTTPException, BackgroundTasks

from app.db.schema import (
    User, Tenant, TenantType, TenantConnection,
    SupplierProfile, ConnectionStatus, AuditAction,
    RelationshipType
)
from app.models.tenant_connection import (
    ConnectionReinvite, InviteDetails, PublicTenantRead
)
from app.models.supplier_profile import SupplierProfileRead
from app.core.audit import _perform_audit_log


class TenantConnectionService:
    def __init__(self, session: Session):
        self.session = session

    def _get_active_tenant(self, user: User) -> Tenant:
        tenant_id = getattr(user, "_tenant_id", None)
        if not tenant_id:
            raise HTTPException(
                status_code=403, detail="No active tenant context.")
        return self.session.get(Tenant, tenant_id)

    # ==========================================================================
    # PUBLIC / ANONYMOUS ACTIONS
    # ==========================================================================

    def validate_invite_token(self, token: str) -> InviteDetails:
        """
        Public Utility: Verifies an invite token and returns details to the UI.

        Refactored to be POLYMORPHIC & GENERIC:
        1. Fetches Connection + Requester (Generic Tenant).
        2. Checks Connection.type.
        3. Dynamically fetches the associated Profile (Supplier, Recycler, etc.).
        """
        # Step 1: Fetch the Connection and the Requester
        # We join Tenant on 'requester_tenant_id'
        statement = (
            select(TenantConnection, Tenant)
            .join(Tenant, TenantConnection.requester_tenant_id == Tenant.id)
            .where(TenantConnection.invitation_token == token)
            .where(TenantConnection.status == ConnectionStatus.PENDING)
        )

        result = self.session.exec(statement).first()

        if not result:
            raise HTTPException(
                status_code=404, detail="Invalid or expired invitation link.")

        conn, requester_tenant = result

        # Step 2: Initialize default Target data
        target_name = "Unknown Partner"
        target_country = None
        extra_data = {}

        # Step 3: Switch on Relationship Type to fetch specific Profile
        if conn.type == RelationshipType.SUPPLIER:
            # Check if this connection has a linked SupplierProfile
            # (Note: You might need to check if conn.supplier_profile exists based on your relationship setup)
            if conn.supplier_profile:
                profile = conn.supplier_profile
                target_name = profile.name
                target_country = profile.location_country

        elif conn.type == RelationshipType.RECYCLER:
            # Future logic
            pass

        # Step 4: Return Unified Response using generic requester fields
        return InviteDetails(
            email=conn.invitation_email or "",
            request_note=conn.request_note,

            requester_name=requester_tenant.name,
            requester_handle=requester_tenant.slug,

            relationship_type=conn.type,
            target_name=target_name,
            target_country=target_country,
            profile_data=extra_data
        )

    # ==========================================================================
    # TARGET ACTIONS (The Invited Party)
    # ==========================================================================

    def respond_to_request(
        self,
        user: User,
        connection_id: uuid.UUID,
        accept: bool,
        background_tasks: BackgroundTasks
    ):
        """
        The Target Tenant (Supplier/Recycler) accepts or declines a request.
        """
        target_tenant = self._get_active_tenant(user)

        conn = self.session.exec(
            select(TenantConnection)
            .where(TenantConnection.id == connection_id)
            .where(TenantConnection.target_tenant_id == target_tenant.id)
        ).first()

        if not conn:
            raise HTTPException(
                status_code=404, detail="Connection request not found or you are not the target.")

        old_status = conn.status

        # 1. Update Connection Table
        if accept:
            conn.status = ConnectionStatus.ACTIVE
            conn.invitation_token = None  # Security: Consume token
        else:
            conn.status = ConnectionStatus.REJECTED

        self.session.add(conn)

        # 2. Sync SupplierProfile (Denormalization)
        # If this connection is linked to a SupplierProfile (Address Book), update it.
        if conn.supplier_profile:
            profile = conn.supplier_profile
            profile.supplier_tenant_id = target_tenant.id
            profile.connection_status = conn.status
            profile.retry_count = conn.retry_count
            profile.slug = target_tenant.slug
            profile.invitation_email = conn.invitation_email
            self.session.add(profile)

        self.session.commit()

        # 3. Audit
        background_tasks.add_task(
            _perform_audit_log,
            tenant_id=target_tenant.id,
            user_id=user.id,
            entity_type="TenantConnection",
            entity_id=conn.id,
            action=AuditAction.UPDATE,
            changes={
                "action": "respond_to_request",
                "old_status": old_status,
                "new_status": conn.status,
                "requester_id": str(conn.requester_tenant_id)
            }
        )
        return {"status": conn.status}

    # ==========================================================================
    # REQUESTER ACTIONS (The Brand)
    # ==========================================================================

    def reinvite_supplier(
        self,
        user: User,
        profile_id: uuid.UUID,
        data: ConnectionReinvite,
        background_tasks: BackgroundTasks
    ) -> SupplierProfileRead:
        """
        Resends an invitation explicitly to a Supplier in the Address Book.

        NOTE: The entry point is the 'profile_id' because this action 
        originates from the Supplier Profile UI card.
        """
        requester = self._get_active_tenant(user)

        # 1. Fetch Profile & Connection
        # We start from SupplierProfile to ensure ownership and that we are strictly acting on a Supplier
        profile = self.session.exec(
            select(SupplierProfile)
            .where(SupplierProfile.id == profile_id)
            .where(SupplierProfile.tenant_id == requester.id)
        ).first()

        if not profile or not profile.connection:
            raise HTTPException(
                status_code=404, detail="Supplier profile or connection record not found.")

        conn = profile.connection

        if not conn.status in [ConnectionStatus.PENDING, ConnectionStatus.REJECTED]:
            raise HTTPException(
                status_code=400, detail="Invalid supplier connection status.")

        # 2. Retry Logic Checks
        if conn.retry_count >= 3:
            raise HTTPException(
                status_code=400,
                detail="Maximum retry limit (3) reached. Please contact support."
            )

        target_email = data.invite_email or conn.invitation_email
        if not target_email and not conn.target_tenant_id:
            raise HTTPException(
                status_code=400, detail="No valid destination (Email or Tenant ID) found.")

        # 3. Update Connection Table (The Source of Truth for the Handshake)
        conn.request_note = data.note
        conn.status = ConnectionStatus.PENDING
        conn.retry_count += 1
        conn.invitation_token = secrets.token_urlsafe(
            32)  # Rotate token for security
        if target_email:
            conn.invitation_email = target_email

        self.session.add(conn)

        # 4. Sync SupplierProfile (Denormalization for fast UI reads)
        profile.connection_status = ConnectionStatus.PENDING
        profile.retry_count = conn.retry_count
        if target_email:
            profile.invitation_email = target_email

        self.session.add(profile)

        self.session.commit()
        self.session.refresh(profile)

        # 5. Audit
        background_tasks.add_task(
            _perform_audit_log,
            tenant_id=requester.id,
            user_id=user.id,
            entity_type="TenantConnection",
            entity_id=conn.id,
            action=AuditAction.UPDATE,
            changes={
                "type": "reinvite_supplier",
                "retry_number": conn.retry_count,
                "target": target_email
            }
        )

        # 6. Return the updated Supplier View
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

    # ==========================================================================
    # DIRECTORY SEARCH
    # ==========================================================================

    def search_directory(self, query: str, type_filter: TenantType = TenantType.SUPPLIER, limit: int = 10) -> List[PublicTenantRead]:
        """
        Searches the global tenant registry.
        """
        search_fmt = f"%{query}%"

        statement = (
            select(Tenant)
            .where(or_(col(Tenant.name).ilike(search_fmt), col(Tenant.slug).ilike(search_fmt)))
            .where(Tenant.status == "active")
            .limit(limit)
        )

        if type_filter:
            statement = statement.where(Tenant.type == type_filter)

        tenants = self.session.exec(statement).all()

        return [
            PublicTenantRead(
                id=t.id,
                name=t.name,
                slug=t.slug,
                type=t.type,
                location_country=t.location_country
            ) for t in tenants
        ]
