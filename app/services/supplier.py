import uuid
import secrets
from typing import List
from loguru import logger
from sqlmodel import Session, select, col, func, or_
from fastapi import HTTPException, BackgroundTasks

from app.core.config import settings
from app.core.audit import _perform_audit_log
from app.db.schema import (
    User, Tenant, TenantType, ProductContributionRequest,
    SupplierProfile, TenantConnection, ConnectionStatus, RequestStatus,
    Product, ProductVersion, AuditAction
)
from app.models.supplier import (
    SupplierProfileCreate, SupplierProfileRead, PublicTenantRead,
    SupplierProfileUpdate, InviteDetails, SupplierReinvite,
    ConnectionResponse
)
from app.models.supplier_dashboard import DashboardStats, ConnectionRequestItem


class SupplierService:
    """
    Business logic for managing the Brand-Supplier Network.

    Roles:
    - Brands: Maintain an 'Address Book' (SupplierProfile), send Invites, manage Connections.
    - Suppliers: Receive Invites (TenantConnection), Accept/Decline, search Directory.
    """

    def __init__(self, session: Session):
        self.session = session

    def _get_active_tenant(self, user: User) -> Tenant:
        """
        Helper: Retrieves the active tenant from the user session.
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
        Write Helper: Enforces that the current user represents a BRAND.
        Only Brands can add/edit supplier profiles.
        """
        tenant = self._get_active_tenant(user)
        if tenant.type != TenantType.BRAND:
            raise HTTPException(
                status_code=403,
                detail="Access Forbidden. Only Brands can manage Supplier Address Books."
            )
        return tenant

    # ==========================================================================
    # BRAND ACTIONS (Address Book Management)
    # ==========================================================================

    def list_profiles(self, user: User) -> List[SupplierProfileRead]:
        """
        Lists all suppliers in the Brand's address book with their connection status.
        """
        brand = self._get_brand_context(user)

        profiles = self.session.exec(
            select(SupplierProfile).where(
                SupplierProfile.tenant_id == brand.id)
        ).all()

        results = []
        for p in profiles:
            conn = p.connection

            # Default values for a Profile with no active connection logic (Rare)
            # Using string literal because 'DISCONNECTED' is not in the DB Enum
            status_val = "disconnected"
            handle_val = None
            audit_email = None
            retry_count = 0
            can_reinvite = False

            if conn:
                status_val = conn.status.value  # Get string value of enum
                audit_email = conn.supplier_email_invite
                retry_count = conn.retry_count

                # Logic: Can only reinvite if NOT connected (ACTIVE) and Retries < 3
                if conn.status != ConnectionStatus.ACTIVE and conn.retry_count < 3:
                    can_reinvite = True

                if conn.supplier_tenant_id:
                    real_tenant = self.session.get(
                        Tenant, conn.supplier_tenant_id)
                    if real_tenant:
                        handle_val = real_tenant.slug

            results.append(SupplierProfileRead(
                id=p.id,
                name=p.name,
                description=p.description,
                location_country=p.location_country,
                connection_status=status_val,
                connected_handle=handle_val,
                audit_invite_email=audit_email,
                retry_count=retry_count,
                can_reinvite=can_reinvite
            ))

        return results

    def add_supplier(
        self,
        user: User,
        data: SupplierProfileCreate,
        background_tasks: BackgroundTasks
    ) -> SupplierProfileRead:
        """
        Adds a supplier to the address book and initiates a connection request.
        """
        brand = self._get_brand_context(user)

        # 1. Resolve Target Identity
        target_tenant_id = None
        target_tenant_slug = None

        if data.public_handle:
            # Connecting to existing platform user
            target_tenant = self.session.exec(
                select(Tenant).where(Tenant.slug == data.public_handle)
            ).first()

            if not target_tenant:
                raise HTTPException(
                    status_code=404, detail=f"Company '@{data.public_handle}' not found in directory.")

            if target_tenant.type == TenantType.BRAND:
                raise HTTPException(
                    status_code=400, detail="A Brand cannot add another Brand as a supplier.")

            target_tenant_id = target_tenant.id
            target_tenant_slug = target_tenant.slug

        # 2. Check for Duplicates in Address Book
        existing = self.session.exec(
            select(SupplierProfile)
            .where(SupplierProfile.tenant_id == brand.id)
            .where(SupplierProfile.name == data.name)
        ).first()

        if existing:
            raise HTTPException(
                status_code=409, detail=f"A supplier named '{data.name}' already exists in your list.")

        try:
            # 3. Create Profile Record
            profile = SupplierProfile(
                tenant_id=brand.id,
                connected_tenant_id=target_tenant_id,
                name=data.name,
                description=data.description,
                location_country=data.location_country
            )
            self.session.add(profile)
            self.session.flush()

            # 4. Create Connection Record
            invite_token = None
            # We generate a token if it's an email invite OR a platform invite (for the notification link)
            if data.invite_email or target_tenant_id:
                invite_token = secrets.token_urlsafe(32)

            conn = TenantConnection(
                brand_tenant_id=brand.id,
                supplier_tenant_id=target_tenant_id,
                supplier_profile_id=profile.id,
                invitation_token=invite_token,
                supplier_email_invite=data.invite_email,
                request_note=data.request_note,
                status=ConnectionStatus.PENDING,
                retry_count=0
            )
            self.session.add(conn)
            self.session.commit()
            self.session.refresh(profile)

            # 5. MOCK Notification
            if data.invite_email:
                link = f"{settings.public_dashboard_host}/register?token={invite_token}"
                logger.info(
                    f" [EMAIL SERVICE] Sending invite to {data.invite_email} with link: {link}")

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

            return SupplierProfileRead(
                id=profile.id,
                name=profile.name,
                description=profile.description,
                location_country=profile.location_country,
                connection_status=conn.status,
                connected_handle=target_tenant_slug,
                audit_invite_email=data.invite_email,
                retry_count=0,
                can_reinvite=True
            )

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
        Updates the Alias or Description of a supplier.
        """
        brand = self._get_brand_context(user)

        profile = self.session.exec(
            select(SupplierProfile)
            .where(SupplierProfile.id == profile_id)
            .where(SupplierProfile.tenant_id == brand.id)
        ).first()

        if not profile:
            raise HTTPException(
                status_code=404, detail="Supplier profile not found.")

        # Snapshot for Audit
        old_state = profile.model_dump()

        # Check Name Uniqueness (only if changing)
        if data.name and data.name != profile.name:
            existing = self.session.exec(
                select(SupplierProfile)
                .where(SupplierProfile.tenant_id == brand.id)
                .where(SupplierProfile.name == data.name)
            ).first()
            if existing:
                raise HTTPException(
                    status_code=409, detail="A supplier with this name already exists.")
            profile.name = data.name

        if data.description is not None:
            profile.description = data.description

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

        # Re-fetch connection data for response
        conn = profile.connection
        return SupplierProfileRead(
            id=profile.id,
            name=profile.name,
            description=profile.description,
            location_country=profile.location_country,
            connection_status=conn.status.value if conn else "disconnected",
            connected_handle=None,  # Not needed for simple update return
            audit_invite_email=conn.supplier_email_invite if conn else None,
            retry_count=conn.retry_count if conn else 0,
            can_reinvite=(conn.retry_count < 3) if conn else False
        )

    def disconnect_supplier(
        self,
        user: User,
        profile_id: uuid.UUID,
        background_tasks: BackgroundTasks
    ):
        """
        Handles removing a supplier.
        - If Pending: Hard delete (Cancel invite).
        - If Connected: Soft disconnect (Set status to Disconnected).
        """
        brand = self._get_brand_context(user)

        profile = self.session.exec(
            select(SupplierProfile)
            .where(SupplierProfile.id == profile_id)
            .where(SupplierProfile.tenant_id == brand.id)
        ).first()

        if not profile:
            raise HTTPException(status_code=404, detail="Supplier not found.")

        conn = profile.connection
        snapshot_name = profile.name
        action = AuditAction.UPDATE

        if not conn:
            # Corrupted state, safe to delete
            self.session.delete(profile)
            action = AuditAction.DELETE
        elif conn.status == ConnectionStatus.PENDING or conn.status == ConnectionStatus.DISCONNECTED:
            # Cancel invite or remove old record
            self.session.delete(profile)
            action = AuditAction.DELETE
        elif conn.status == ConnectionStatus.CONNECTED:
            # Don't lose history, just break the link
            conn.status = ConnectionStatus.DISCONNECTED
            conn.invitation_token = None  # Invalidate any active tokens
            self.session.add(conn)
        else:
            # Should not happen
            pass

        self.session.commit()

        background_tasks.add_task(
            _perform_audit_log,
            tenant_id=brand.id,
            user_id=user.id,
            entity_type="SupplierProfile",
            entity_id=profile_id,
            action=action,
            changes={"name": snapshot_name, "status": "disconnected"}
        )
        return {"message": "Supplier disconnected/removed successfully."}

    def reinvite_supplier(
        self,
        user: User,
        profile_id: uuid.UUID,
        data: SupplierReinvite,
        background_tasks: BackgroundTasks
    ) -> SupplierProfileRead:
        """
        Resends an invitation to a Pending or Declined supplier.
        Enforces a maximum of 3 retries.
        """
        brand = self._get_brand_context(user)

        profile = self.session.exec(
            select(SupplierProfile).where(SupplierProfile.id == profile_id)
        ).first()

        if not profile or not profile.connection:
            raise HTTPException(
                status_code=404, detail="Connection record not found.")

        conn = profile.connection

        if conn.status == ConnectionStatus.ACTIVE:
            raise HTTPException(
                status_code=400, detail="Supplier is already connected.")

        # --- RETRY CHECK ---
        if conn.retry_count >= 3:
            raise HTTPException(
                status_code=400,
                detail="Maximum retry limit (3) reached for this supplier. Please contact support to reset."
            )

        # Update Logic
        target_email = data.invite_email or conn.supplier_email_invite
        if not target_email and not conn.supplier_tenant_id:
            raise HTTPException(
                status_code=400, detail="No valid destination (Email or Tenant ID) found.")

        # Update connection
        conn.request_note = data.note
        conn.status = ConnectionStatus.PENDING
        conn.retry_count += 1

        # Security: Rotate token
        conn.invitation_token = secrets.token_urlsafe(32)

        if target_email:
            conn.supplier_email_invite = target_email

        self.session.add(conn)
        self.session.commit()

        # Audit
        background_tasks.add_task(
            _perform_audit_log,
            tenant_id=brand.id,
            user_id=user.id,
            entity_type="TenantConnection",
            entity_id=conn.id,
            action=AuditAction.UPDATE,
            changes={"type": "reinvite", "retry_number": conn.retry_count}
        )

        return SupplierProfileRead(
            id=profile.id,
            name=profile.name,
            description=profile.description,
            location_country=profile.location_country,
            connection_status=conn.status,
            audit_invite_email=target_email,
            retry_count=conn.retry_count,
            can_reinvite=(conn.retry_count < 3)
        )

    # ==========================================================================
    # SUPPLIER ACTIONS
    # ==========================================================================

    def list_incoming_requests(self, user: User) -> List[ConnectionResponse]:
        """
        Lists connection requests where the current user (Supplier) is the target.
        """
        tenant = self._get_active_tenant(user)  # Check if user has tenant

        # Filter: I am the supplier, Status is Pending
        statement = (
            select(TenantConnection, Tenant)
            .join(Tenant, TenantConnection.brand_tenant_id == Tenant.id)
            .where(TenantConnection.supplier_tenant_id == tenant.id)
            .where(TenantConnection.status == ConnectionStatus.PENDING)
        )
        results = self.session.exec(statement).all()

        return [
            ConnectionResponse(
                connection_id=c.id,
                brand_name=t.name,
                invited_at=c.created_at
            ) for c, t in results
        ]

    def respond_to_request(
        self,
        user: User,
        connection_id: uuid.UUID,
        accept: bool,
        background_tasks: BackgroundTasks
    ):
        """
        Accepts or Declines a Brand's connection request.
        """
        tenant = self._get_active_tenant(user)

        conn = self.session.exec(
            select(TenantConnection)
            .where(TenantConnection.id == connection_id)
            .where(TenantConnection.supplier_tenant_id == tenant.id)
        ).first()

        if not conn:
            raise HTTPException(
                status_code=404, detail="Connection request not found.")

        old_status = conn.status
        if accept:
            conn.status = ConnectionStatus.ACTIVE
            conn.invitation_token = None  # Consume token
        else:
            conn.status = ConnectionStatus.REJECTED

        self.session.add(conn)
        self.session.commit()

        background_tasks.add_task(
            _perform_audit_log,
            tenant_id=tenant.id,
            user_id=user.id,
            entity_type="TenantConnection",
            entity_id=conn.id,
            action=AuditAction.UPDATE,
            changes={"old_status": old_status, "new_status": conn.status}
        )
        return {"status": conn.status}

    # ==========================================================================
    # DIRECTORY & UTILS
    # ==========================================================================

    def search_directory(self, query: str, limit: int = 10) -> List[PublicTenantRead]:
        """
        Searches the global tenant registry for Suppliers (excluding Brands).
        """
        search_fmt = f"%{query}%"
        tenants = self.session.exec(
            select(Tenant)
            .where(or_(col(Tenant.name).ilike(search_fmt), col(Tenant.slug).ilike(search_fmt)))
            # STRICT: Only Suppliers
            .where(Tenant.type == TenantType.SUPPLIER)
            .where(Tenant.status == "active")
            .limit(limit)
        ).all()
        return [PublicTenantRead(name=t.name, slug=t.slug, type=t.type, location_country=t.location_country) for t in tenants]

    def validate_invite_token(self, token: str) -> InviteDetails:
        """
        Public Utility: Verifies an invite token and returns details to the UI.
        """
        statement = (
            select(TenantConnection, SupplierProfile, Tenant)
            .join(SupplierProfile, TenantConnection.supplier_profile_id == SupplierProfile.id)
            .join(Tenant, TenantConnection.brand_tenant_id == Tenant.id)
            .where(TenantConnection.invitation_token == token)
            .where(TenantConnection.status == ConnectionStatus.PENDING)
        )
        result = self.session.exec(statement).first()
        if not result:
            raise HTTPException(
                status_code=404, detail="Invalid or expired invitation link.")

        conn, profile, brand = result
        return InviteDetails(
            email=conn.supplier_email_invite,
            brand_name=brand.name,
            brand_handle=brand.slug,
            supplier_name=profile.name,
            supplier_country=profile.location_country
        )

    # ==========================================================================
    # DASHBOARD LOGIC
    # ==========================================================================

    def get_dashboard_stats(self, user: User) -> DashboardStats:
        """
        Calculates KPIs for the Supplier Dashboard.
        """
        tenant = self._get_active_tenant(user)

        # 1. Connection Stats
        pending_invites = self.session.exec(
            select(func.count(TenantConnection.id))
            .where(TenantConnection.supplier_tenant_id == tenant.id)
            .where(TenantConnection.status == ConnectionStatus.PENDING)
        ).one()

        connected_brands = self.session.exec(
            select(func.count(TenantConnection.id))
            .where(TenantConnection.supplier_tenant_id == tenant.id)
            .where(TenantConnection.status == ConnectionStatus.ACTIVE)
        ).one()

        # 2. Task Stats (Data Requests)
        # Active = Sent, In Progress, Changes Requested
        active_tasks = self.session.exec(
            select(func.count(ProductContributionRequest.id))
            .where(ProductContributionRequest.supplier_tenant_id == tenant.id)
            .where(ProductContributionRequest.status.in_([
                RequestStatus.SENT,
                RequestStatus.IN_PROGRESS,
                RequestStatus.CHANGES_REQUESTED
            ]))
        ).one()

        completed_tasks = self.session.exec(
            select(func.count(ProductContributionRequest.id))
            .where(ProductContributionRequest.supplier_tenant_id == tenant.id)
            .where(ProductContributionRequest.status == RequestStatus.COMPLETED)
        ).one()

        return DashboardStats(
            pending_invites=pending_invites,
            active_tasks=active_tasks,
            completed_tasks=completed_tasks,
            connected_brands=connected_brands
        )

    def get_connection_requests(self, user: User) -> List[ConnectionRequestItem]:
        """
        Fetches pending B2B invites enriched with Brand details.
        """
        tenant = self._get_active_tenant(user)

        statement = (
            select(TenantConnection, Tenant)
            .join(Tenant, TenantConnection.brand_tenant_id == Tenant.id)
            .where(TenantConnection.supplier_tenant_id == tenant.id)
            .where(TenantConnection.status == ConnectionStatus.PENDING)
            .order_by(TenantConnection.created_at.desc())
        )

        results = self.session.exec(statement).all()

        return [
            ConnectionRequestItem(
                id=conn.id,
                brand_name=brand.name,
                brand_handle=brand.slug,
                invited_at=conn.created_at,
                note=conn.request_note
            )
            for conn, brand in results
        ]
