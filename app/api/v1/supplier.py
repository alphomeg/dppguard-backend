import uuid
from typing import List
from fastapi import APIRouter, Depends, status, BackgroundTasks

from app.core.dependencies import get_current_user, get_supplier_service
from app.db.schema import User
from app.services.supplier import SupplierService
from app.models.supplier import (
    SupplierProfileCreate, SupplierProfileRead, SupplierProfileUpdate,
    InviteDetails, ConnectionResponse, DecisionPayload, SupplierReinvite,
    PublicTenantRead
)
from app.models.supplier_dashboard import (
    DashboardStats, ConnectionRequestItem
)

router = APIRouter()

# --- DASHBOARD & READS ---


@router.get(
    "/dashboard/stats",
    response_model=DashboardStats,
    summary="Get Dashboard KPIs",
    description="Returns counts for tasks and connections."
)
def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    return service.get_dashboard_stats(current_user)


@router.get(
    "/dashboard/requests",
    response_model=List[ConnectionRequestItem],
    summary="Get Pending Connection Requests",
    description="Returns list of brands waiting for connection approval, including personal notes."
)
def get_connection_requests(
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    return service.get_connection_requests(current_user)


@router.get(
    "/",
    response_model=List[SupplierProfileRead],
    summary="List Address Book",
    description="Returns all suppliers configured by the current Brand, including connection status."
)
def list_suppliers(
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    return service.list_profiles(current_user)


@router.get(
    "/directory/search",
    response_model=List[PublicTenantRead],
    summary="Search Directory",
    description="Search for existing Suppliers on the platform by name or handle."
)
def search_directory(
    q: str,
    service: SupplierService = Depends(get_supplier_service),
    current_user: User = Depends(get_current_user)
):
    return service.search_directory(q)


@router.get(
    "/invitation/{token}",
    response_model=InviteDetails,
    summary="Verify Invite Token",
    description="Public endpoint to validate an invite link before registration."
)
def verify_invitation(
    token: str,
    service: SupplierService = Depends(get_supplier_service)
):
    return service.validate_invite_token(token)

# --- WRITES (WITH AUDIT) ---


@router.post(
    "/",
    response_model=SupplierProfileRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add Supplier",
    description="Adds a supplier to the address book. If an email is provided, sends an invitation."
)
def add_supplier(
    data: SupplierProfileCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    return service.add_supplier(current_user, data, background_tasks)


@router.patch(
    "/{profile_id}",
    response_model=SupplierProfileRead,
    summary="Update Profile",
    description="Update the alias or internal notes for a supplier."
)
def update_supplier(
    profile_id: uuid.UUID,
    data: SupplierProfileUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    return service.update_profile(current_user, profile_id, data, background_tasks)


@router.delete(
    "/{profile_id}",
    summary="Disconnect Supplier",
    description="Removes a supplier. If invite is pending, it is cancelled. If connected, the link is severed."
)
def disconnect_supplier(
    profile_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    return service.disconnect_supplier(current_user, profile_id, background_tasks)


@router.post(
    "/{profile_id}/reinvite",
    response_model=SupplierProfileRead,
    summary="Resend Invitation",
    description="Resends the invite email. Limited to 3 retries per connection."
)
def resend_invitation(
    profile_id: uuid.UUID,
    data: SupplierReinvite,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    return service.reinvite_supplier(current_user, profile_id, data, background_tasks)

# --- SUPPLIER ACTIONS ---


@router.get(
    "/requests/incoming",
    response_model=List[ConnectionResponse],
    summary="List Incoming Invites",
    description="For Suppliers: View connection requests from Brands."
)
def get_incoming_requests(
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    return service.list_incoming_requests(current_user)


@router.post(
    "/requests/{connection_id}/respond",
    summary="Respond to Invite",
    description="For Suppliers: Accept or Decline a connection request."
)
def respond_to_invite(
    connection_id: uuid.UUID,
    payload: DecisionPayload,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    return service.respond_to_request(current_user, connection_id, payload.accept, background_tasks)
