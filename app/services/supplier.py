from typing import List
import uuid
from loguru import logger
from sqlmodel import Session, select, col
from fastapi import HTTPException

from app.db.schema import (
    User, Tenant, TenantType,
    SupplierProfile, TenantConnection, ConnectionStatus
)
from app.models.supplier import SupplierProfileCreate, SupplierProfileRead, PublicTenantRead, SupplierProfileUpdate


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
                    # In high-perf scenarios, use a JOIN in the main query.
                    # Here we lazily load for clarity.
                    real_tenant = self.session.get(
                        Tenant, conn.supplier_tenant_id)
                    if real_tenant:
                        handle_val = real_tenant.slug

            results.append(SupplierProfileRead(
                id=p.id,
                name=p.name,
                location_country=p.location_country,
                connection_status=status_val,
                connected_handle=handle_val,
                audit_invite_email=audit_email
            ))

        return results

    def add_supplier(self, user: User, data: SupplierProfileCreate) -> SupplierProfileRead:
        brand_id = self._get_brand_id(user)

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
                location_country=data.location_country
            )
            self.session.add(profile)
            self.session.flush()

            # 2. Create Connection
            conn = TenantConnection(
                brand_tenant_id=brand_id,
                supplier_tenant_id=target_tenant_id,
                supplier_profile_id=profile.id,

                # STORE EMAIL HERE ONLY (Audit/Invite)
                supplier_email_invite=data.invite_email,

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

            return SupplierProfileRead(
                id=profile.id,
                name=profile.name,
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

        # 2. Duplicate Name Check (if renaming)
        if data.name and data.name != profile.name:
            existing = self.session.exec(
                select(SupplierProfile)
                .where(SupplierProfile.tenant_id == brand_id)
                .where(SupplierProfile.name == data.name)
            ).first()
            if existing:
                raise HTTPException(
                    status_code=409, detail="A supplier with this name already exists.")

            profile.name = data.name
            self.session.add(profile)
            self.session.commit()
            self.session.refresh(profile)

        # 3. Return formatted response
        # (Re-using logic to fetch connection details for the Read model)
        conn = profile.connection
        handle_val = None

        if conn and conn.supplier_tenant_id:
            real_tenant = self.session.get(Tenant, conn.supplier_tenant_id)
            if real_tenant:
                handle_val = real_tenant.slug

        return SupplierProfileRead(
            id=profile.id,
            name=profile.name,
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
