from typing import List
from sqlmodel import Session, select, func
from fastapi import HTTPException

from app.db.schema import (
    User, Tenant, TenantType, TenantConnection,
    ConnectionStatus, ProductContributionRequest, RequestStatus,
)
from app.models.supplier_dashboard import (
    DashboardStats, ConnectionRequestItem
)


class SupplierDashboardService:
    def __init__(self, session: Session):
        self.session = session

    def _get_supplier_context(self, user: User) -> Tenant:
        """
        Helper: Strictly enforces that the user belongs to a SUPPLIER Tenant.
        """
        tenant_id = getattr(user, "_tenant_id", None)
        if not tenant_id:
            raise HTTPException(
                status_code=403, detail="No active tenant context.")

        tenant = self.session.get(Tenant, tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        if tenant.type != TenantType.SUPPLIER:
            raise HTTPException(
                status_code=403,
                detail="Access Forbidden. Only Suppliers can access this dashboard."
            )
        return tenant

    # ==========================================================================
    # MAIN DASHBOARD API
    # ==========================================================================

    def get_dashboard_stats(self, user: User) -> DashboardStats:
        """
        Calculates aggregate KPIs for the Supplier Dashboard.
        """
        tenant = self._get_supplier_context(user)

        # 1. Connection Stats (Where I am the Target)
        pending_invites = self.session.exec(
            select(func.count(TenantConnection.id))
            .where(TenantConnection.target_tenant_id == tenant.id)
            .where(TenantConnection.status == ConnectionStatus.PENDING)
        ).one()

        connected_brands = self.session.exec(
            select(func.count(TenantConnection.id))
            .where(TenantConnection.target_tenant_id == tenant.id)
            .where(TenantConnection.status == ConnectionStatus.ACTIVE)
        ).one()

        # 2. Task Stats (ProductContributionRequest)
        # Assuming table has: supplier_tenant_id, status
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

    def list_pending_invites(self, user: User) -> List[ConnectionRequestItem]:
        """
        Fetches the list of Brands waiting to connect.
        """
        tenant = self._get_supplier_context(user)

        # Join Tenant to get the Brand's name/handle
        statement = (
            select(TenantConnection, Tenant)
            .join(Tenant, TenantConnection.requester_tenant_id == Tenant.id)
            .where(TenantConnection.target_tenant_id == tenant.id)
            .where(TenantConnection.status == ConnectionStatus.PENDING)
            .order_by(TenantConnection.created_at.desc())
        )

        results = self.session.exec(statement).all()

        return [
            ConnectionRequestItem(
                id=conn.id,
                brand_name=requester.name,
                brand_handle=requester.slug,
                invited_at=conn.created_at,
                note=conn.request_note
            )
            for conn, requester in results
        ]
