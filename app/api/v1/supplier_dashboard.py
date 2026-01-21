from typing import List
from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_current_user, get_supplier_dashboard_service
from app.db.schema import User
from app.services.supplier_dashboard import SupplierDashboardService
from app.models.supplier_dashboard import (
    DashboardStats, ConnectionRequestItem
)

router = APIRouter()


@router.get(
    "/stats",
    response_model=DashboardStats,
    status_code=status.HTTP_200_OK,
    summary="Get Dashboard KPIs",
    description="Returns counts for tasks and connections."
)
def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    service: SupplierDashboardService = Depends(get_supplier_dashboard_service)
):
    return service.get_dashboard_stats(current_user)


@router.get(
    "/requests",
    response_model=List[ConnectionRequestItem],
    status_code=status.HTTP_200_OK,
    summary="Get Pending Connection Requests",
    description="Returns list of brands waiting for connection approval, including personal notes."
)
def get_connection_requests(
    current_user: User = Depends(get_current_user),
    service: SupplierDashboardService = Depends(get_supplier_dashboard_service)
):
    return service.list_pending_invites(current_user)
