from typing import List
import uuid
import secrets
from loguru import logger
from sqlmodel import Session, select, col, func
from fastapi import HTTPException

from app.core.config import settings
from app.db.schema import (
    User, Tenant, TenantType, DataContributionRequest,
    SupplierProfile, TenantConnection, ConnectionStatus, RequestStatus,
    Product, ProductVersion
)
from app.models.supplier import SupplierProfileCreate, SupplierProfileRead, PublicTenantRead, SupplierProfileUpdate, InviteDetails, SupplierReinvite
from app.models.dashboard import DashboardStats, ConnectionRequestItem, ProductTaskItem


class SupplierService:
    def __init__(self, session: Session):
        self.session = session

    def _get_brand_id(self, user: User) -> uuid.UUID:
        tenant_id = getattr(user, "_tenant_id", None)
        if not tenant_id:
            raise HTTPException(403, "No active tenant.")
        tenant = self.session.get(Tenant, tenant_id)
        if tenant.type not in [TenantType.BRAND, TenantType.HYBRID]:
            raise HTTPException(403, "Action restricted to Brands.")
        return tenant_id

    def list_profiles(self, user: User) -> List[SupplierProfileRead]:
        brand_id = self._get_brand_id(user)

        # 1. Get Profiles
        profiles = self.session.exec(
            select(SupplierProfile).where(
                SupplierProfile.tenant_id == brand_id)
        ).all()

        results = []
        for p in profiles:
            conn = p.connection  # 1:1 Access

            # Defaults
            status_val = ConnectionStatus.DISCONNECTED
            handle_val = None
            audit_email = None

            if conn:
                status_val = conn.status
                audit_email = conn.supplier_email_invite  # Only exists if invited via email

                # If actually connected to a Tenant, fetch the Handle
                if conn.supplier_tenant_id:
                    real_tenant = self.session.get(
                        Tenant, conn.supplier_tenant_id)
                    if real_tenant:
                        handle_val = real_tenant.slug

            results.append(SupplierProfileRead(
                id=p.id,
                name=p.name,
                # MAP NEW FIELD
                description=p.description,
                location_country=p.location_country,
                connection_status=status_val,
                connected_handle=handle_val,
                audit_invite_email=audit_email
            ))

        return results

    def add_supplier(self, user: User, data: SupplierProfileCreate) -> SupplierProfileRead:
        brand_id = self._get_brand_id(user)
        brand = self.session.get(Tenant, brand_id)

        # A. Resolve Identity (Handle vs Email)
        target_tenant_id = None
        target_tenant_slug = None

        if data.public_handle:
            # 1. Lookup Tenant
            target_tenant = self.session.exec(
                select(Tenant).where(Tenant.slug == data.public_handle)
            ).first()

            if not target_tenant:
                raise HTTPException(
                    404, f"Company '@{data.public_handle}' not found.")
            if target_tenant.type == TenantType.BRAND:
                raise HTTPException(400, "Cannot connect to another Brand.")

            target_tenant_id = target_tenant.id
            target_tenant_slug = target_tenant.slug

        # B. Check Duplicates (Name)
        existing = self.session.exec(
            select(SupplierProfile)
            .where(SupplierProfile.tenant_id == brand_id)
            .where(SupplierProfile.name == data.name)
        ).first()

        if existing:
            raise HTTPException(409, f"Profile '{data.name}' already exists.")

        try:
            # --- START TRANSACTION ---

            # 1. Create Profile (No Email stored here)
            profile = SupplierProfile(
                tenant_id=brand_id,
                connected_tenant_id=target_tenant_id,
                name=data.name,
                # SAVE NEW FIELD
                description=data.description,
                location_country=data.location_country
            )
            self.session.add(profile)
            self.session.flush()

            # 2. Generate Token if Invite
            invite_token = None
            if data.invite_email:
                invite_token = secrets.token_urlsafe(
                    32)  # High entropy secure token

            # 2. Create Connection
            conn = TenantConnection(
                brand_tenant_id=brand_id,
                supplier_tenant_id=target_tenant_id,
                supplier_profile_id=profile.id,
                invitation_token=invite_token,  # Store it
                # STORE EMAIL HERE ONLY (Audit/Invite)
                supplier_email_invite=data.invite_email,
                request_note=data.request_note,

                status=ConnectionStatus.PENDING
            )
            self.session.add(conn)
            self.session.commit()
            self.session.refresh(profile)

            # 3. Notification Logic
            if target_tenant_id:
                logger.info(
                    f"App Notification -> Tenant: {target_tenant_slug}")
            elif data.invite_email:
                logger.info(f"Email Invite -> {data.invite_email}")

            if target_tenant_id:
                logger.info(
                    f"System Notification -> Tenant: {target_tenant_slug}")
            elif data.invite_email:
                # --- PRINT THE LINK TO CONSOLE ---
                invite_link = f"{settings.public_dashboard_host}/register?token={invite_token}"

                print("\n" + "="*60)
                print(f"📧 EMAIL MOCK: Sending Invite to {data.invite_email}")
                print(f"🔗 LINK: {invite_link}")
                print(
                    f"👋 MESSAGE: {brand.name} has invited you to join the platform.")
                print("="*60 + "\n")

                logger.info(f"Invite Link generated for {data.invite_email}")

            return SupplierProfileRead(
                id=profile.id,
                name=profile.name,
                # RETURN IT
                description=profile.description,
                location_country=profile.location_country,
                connection_status=conn.status,
                connected_handle=target_tenant_slug,
                audit_invite_email=data.invite_email
            )

        except Exception as e:
            self.session.rollback()
            logger.error(f"Add Supplier Error: {e}")
            raise HTTPException(500, "Failed to add supplier.")

    def search_directory(self, query: str, limit: int = 10) -> List[PublicTenantRead]:
        """
            Search for potential suppliers by Name or Slug.
            Excludes other Brands to keep the graph clean.
            """
        # Case-insensitive search
        search_fmt = f"%{query}%"

        statement = (
            select(Tenant)
            .where(
                (col(Tenant.name).ilike(search_fmt)) |
                (col(Tenant.slug).ilike(search_fmt))
            )
            .where(Tenant.type.in_([TenantType.SUPPLIER, TenantType.HYBRID]))
            .where(Tenant.status == "active")
            .limit(limit)
        )

        tenants = self.session.exec(statement).all()

        return [
            PublicTenantRead(
                name=t.name,
                slug=t.slug,
                type=t.type,
                location_country=t.location_country
            )
            for t in tenants
        ]

    def update_profile(self, user: User, profile_id: uuid.UUID, data: SupplierProfileUpdate) -> SupplierProfileRead:
        brand_id = self._get_brand_id(user)

        # 1. Fetch Profile
        profile = self.session.exec(
            select(SupplierProfile)
            .where(SupplierProfile.id == profile_id)
            .where(SupplierProfile.tenant_id == brand_id)
        ).first()

        if not profile:
            raise HTTPException(
                status_code=404, detail="Supplier profile not found.")

        # 2. Update Fields (Name & Description)
        is_updated = False

        if data.name and data.name != profile.name:
            # Duplicate Check only if name changes
            existing = self.session.exec(
                select(SupplierProfile)
                .where(SupplierProfile.tenant_id == brand_id)
                .where(SupplierProfile.name == data.name)
            ).first()
            if existing:
                raise HTTPException(
                    status_code=409, detail="A supplier with this name already exists.")
            profile.name = data.name
            is_updated = True

        # UPDATE LOGIC FOR DESCRIPTION
        if data.description is not None:
            profile.description = data.description
            is_updated = True

        if is_updated:
            self.session.add(profile)
            self.session.commit()
            self.session.refresh(profile)

        # 3. Return formatted response
        conn = profile.connection
        handle_val = None

        if conn and conn.supplier_tenant_id:
            real_tenant = self.session.get(Tenant, conn.supplier_tenant_id)
            if real_tenant:
                handle_val = real_tenant.slug

        return SupplierProfileRead(
            id=profile.id,
            name=profile.name,
            # RETURN IT
            description=profile.description,
            location_country=profile.location_country,
            connection_status=conn.status if conn else ConnectionStatus.DISCONNECTED,
            connected_handle=handle_val,
            audit_invite_email=conn.supplier_email_invite if conn else None
        )

    def disconnect_supplier(self, user: User, profile_id: uuid.UUID):
        """
        Handles the 'Delete' action.
        - Pending Invites -> Cancelled (Deleted)
        - Active Connections -> Disconnected (Status Change)
        - Already Disconnected -> Removed (Deleted)
        """
        brand_id = self._get_brand_id(user)

        profile = self.session.exec(
            select(SupplierProfile)
            .where(SupplierProfile.id == profile_id)
            .where(SupplierProfile.tenant_id == brand_id)
        ).first()

        if not profile:
            raise HTTPException(status_code=404, detail="Supplier not found.")

        conn = profile.connection  # 1:1 Access

        # SCENARIO A: No Connection or Already Disconnected -> Clean up (Hard Delete)
        if not conn or conn.status == ConnectionStatus.DISCONNECTED:
            # Cascade deletes connection if exists
            self.session.delete(profile)
            self.session.commit()
            return {"message": "Supplier removed from address book."}

        # SCENARIO B: Pending Invite -> Cancel (Hard Delete)
        if conn.status == ConnectionStatus.PENDING:
            self.session.delete(profile)
            self.session.commit()
            return {"message": "Invitation cancelled and supplier removed."}

        # SCENARIO C: Active Connection -> Disconnect (Soft Delete)
        if conn.status == ConnectionStatus.CONNECTED:
            conn.status = ConnectionStatus.DISCONNECTED
            self.session.add(conn)
            self.session.commit()
            return {"message": "Supplier connection terminated. Profile kept for records."}

        # Fallback
        return {"message": "Action completed."}

    def validate_invite_token(self, token: str) -> InviteDetails:
        """
        Called by the Frontend Registration page to pre-fill data.
        """
        # 1. Find the connection & join with Profile + Brand
        # We need the Profile for the 'Name/Country' and Brand for 'Brand Name'
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

    def list_incoming_requests(self, user: User):
        """
        For SUPPLIERS: List requests from Brands wanting to connect.
        """
        # Get the Supplier's Tenant ID
        tenant_id = getattr(user, "_tenant_id", None)

        # Query: Find connections where I am the target (supplier_tenant_id)
        # AND status is PENDING
        statement = (
            select(TenantConnection, Tenant)
            .join(Tenant, TenantConnection.brand_tenant_id == Tenant.id)
            .where(TenantConnection.supplier_tenant_id == tenant_id)
            .where(TenantConnection.status == ConnectionStatus.PENDING)
        )

        results = self.session.exec(statement).all()

        # Format for UI
        incoming = []
        for conn, brand in results:
            incoming.append({
                "connection_id": conn.id,
                "brand_name": brand.name,
                "brand_slug": brand.slug,
                "invited_at": conn.created_at,
                "invite_email": conn.supplier_email_invite
            })

        return incoming

    def respond_to_request(self, user: User, connection_id: uuid.UUID, accept: bool):
        """
        For SUPPLIERS: Accept or Decline a connection.
        """
        tenant_id = getattr(user, "_tenant_id", None)

        conn = self.session.exec(
            select(TenantConnection)
            .where(TenantConnection.id == connection_id)
            .where(TenantConnection.supplier_tenant_id == tenant_id)
        ).first()

        if not conn:
            raise HTTPException(404, "Connection request not found.")

        if conn.status != ConnectionStatus.PENDING:
            raise HTTPException(400, f"Request is already {conn.status}.")

        if accept:
            conn.status = ConnectionStatus.CONNECTED
            # Nullify the token now that it's used/accepted
            conn.invitation_token = None
            logger.info(
                f"Supplier {tenant_id} ACCEPTED connection from Brand {conn.brand_tenant_id}")
        else:
            conn.status = ConnectionStatus.DECLINED
            logger.info(
                f"Supplier {tenant_id} DECLINED connection from Brand {conn.brand_tenant_id}")

        self.session.add(conn)
        self.session.commit()
        return {"status": conn.status}

    def reinvite_supplier(self, user: User, profile_id: uuid.UUID, data: SupplierReinvite) -> SupplierProfileRead:
        brand_id = self._get_brand_id(user)
        brand = self.session.get(Tenant, brand_id)

        # 1. Fetch Profile & Connection
        profile = self.session.exec(
            select(SupplierProfile)
            .where(SupplierProfile.id == profile_id)
            .where(SupplierProfile.tenant_id == brand_id)
        ).first()

        if not profile:
            raise HTTPException(
                status_code=404, detail="Supplier profile not found.")

        conn = profile.connection  # 1:1

        # 2. Validation
        if not conn:
            raise HTTPException(
                status_code=400, detail="Cannot re-invite a supplier with no prior connection record.")

        if conn.status == ConnectionStatus.CONNECTED:
            raise HTTPException(
                status_code=400, detail="Supplier is already connected. No need to re-invite.")

        # 3. Determine Target / Identity
        # We check if a new email was provided, or fall back to the old one.
        target_email = data.invite_email or conn.supplier_email_invite
        target_tenant_id = conn.supplier_tenant_id

        # LOGIC CHANGE:
        # We only fail if we have NEITHER an email NOR a connected tenant ID.
        # It is valid to re-invite a Tenant ID without an email (Internal Notification).
        if not target_email and not target_tenant_id:
            raise HTTPException(
                status_code=400,
                detail="No email address available. Please provide an email to send the invitation."
            )

        # 4. Update Connection State
        if target_email:
            conn.supplier_email_invite = target_email  # Update if we have one

        conn.request_note = data.note
        # Reset to Pending so it shows in their dashboard
        conn.status = ConnectionStatus.PENDING

        # Security: Rotate the token (Valid for both email links and API verification)
        new_token = secrets.token_urlsafe(32)
        conn.invitation_token = new_token

        self.session.add(conn)
        self.session.commit()
        self.session.refresh(conn)

        # 5. Notifications

        # A. Email Notification (If email exists)
        if target_email:
            invite_link = f"{settings.public_dashboard_host}/register?token={new_token}"
            print("\n" + "="*60)
            print(f"🔄 RE-INVITE (EMAIL): Sending to {target_email}")
            if data.note:
                print(f"📝 NOTE: {data.note}")
            print(f"🔗 LINK: {invite_link}")
            print("="*60 + "\n")

        # B. System Notification (If Tenant ID exists)
        if target_tenant_id:
            # In a real app, you might create a Notification table record here
            print(
                f"🔔 RE-INVITE (SYSTEM): Notification queued for Tenant {target_tenant_id}")

        # 6. Return Updated Profile View
        handle_val = None
        if conn.supplier_tenant_id:
            real_tenant = self.session.get(Tenant, conn.supplier_tenant_id)
            if real_tenant:
                handle_val = real_tenant.slug

        return SupplierProfileRead(
            id=profile.id,
            name=profile.name,
            # RETURN IT
            description=profile.description,
            location_country=profile.location_country,
            connection_status=conn.status,
            connected_handle=handle_val,
            audit_invite_email=target_email  # Might be None if handle-only
        )

    def get_dashboard_stats(self, user: User) -> DashboardStats:
        """
        Calculates KPIs for the Supplier Dashboard.
        """
        supplier_id = getattr(user, "_tenant_id", None)

        pending_invites = self.session.exec(
            select(func.count(TenantConnection.id))
            .where(TenantConnection.supplier_tenant_id == supplier_id)
            .where(TenantConnection.status == ConnectionStatus.PENDING)
        ).one()

        connected_brands = self.session.exec(
            select(func.count(TenantConnection.id))
            .where(TenantConnection.supplier_tenant_id == supplier_id)
            .where(TenantConnection.status == ConnectionStatus.CONNECTED)
        ).one()

        active_tasks = self.session.exec(
            select(func.count(DataContributionRequest.id))
            .where(DataContributionRequest.supplier_tenant_id == supplier_id)
            .where(DataContributionRequest.status.in_([
                RequestStatus.SENT, RequestStatus.IN_PROGRESS, RequestStatus.CHANGES_REQUESTED
            ]))
        ).one()

        completed_tasks = self.session.exec(
            select(func.count(DataContributionRequest.id))
            .where(DataContributionRequest.supplier_tenant_id == supplier_id)
            .where(DataContributionRequest.status == RequestStatus.COMPLETED)
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
        supplier_id = getattr(user, "_tenant_id", None)

        statement = (
            select(TenantConnection, Tenant)
            .join(Tenant, TenantConnection.brand_tenant_id == Tenant.id)
            .where(TenantConnection.supplier_tenant_id == supplier_id)
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

    def get_product_tasks(self, user: User) -> List[ProductTaskItem]:
        supplier_id = getattr(user, "_tenant_id", None)

        # Join: Request -> Version -> Product -> Brand(Tenant)
        statement = (
            select(DataContributionRequest, ProductVersion, Product, Tenant)
            .join(ProductVersion, DataContributionRequest.current_version_id == ProductVersion.id)
            .join(Product, ProductVersion.product_id == Product.id)
            .join(Tenant, DataContributionRequest.brand_tenant_id == Tenant.id)
            .where(DataContributionRequest.supplier_tenant_id == supplier_id)
            .order_by(DataContributionRequest.updated_at.desc())
        )

        results = self.session.exec(statement).all()

        tasks = []
        for req, version, product, brand in results:
            # Calculate Completion %
            fields_to_check = [
                version.manufacturing_country,
                version.total_carbon_footprint_kg,
                version.total_water_usage_liters,
                version.total_energy_mj,
                version.recycling_instructions
            ]
            filled = len(
                [f for f in fields_to_check if f is not None and f != ""])
            total = len(fields_to_check)
            progress = int((filled / total) * 100) if total > 0 else 0

            # Mock Due Date (Created + 14 days) or use actual due_date if set
            mock_due_date = req.due_date if req.due_date else req.created_at

            tasks.append(ProductTaskItem(
                id=req.id,
                # FIXED: Used version.product_name instead of product.name
                product_name=version.product_name,
                version_name=version.version_name,
                sku=product.sku,
                brand_name=brand.name,
                status=req.status,
                completion_percent=progress,
                due_date=mock_due_date,
                created_at=req.created_at
            ))

        return tasks
