import uuid
from app.models.supplier import SupplierProfileUpdate  # Import new model
from app.models.supplier import PublicTenantRead  # Import new model
from typing import List
from fastapi import APIRouter, Depends, status
from loguru import logger

from app.core.dependencies import get_current_user, get_supplier_service
from app.models.supplier import (
    SupplierProfileCreate, SupplierProfileRead,
    InviteDetails, ConnectionResponse, DecisionPayload,
    SupplierReinvite
)
from app.models.dashboard import (
    DashboardStats, ConnectionRequestItem, ProductTaskItem
)
from app.db.schema import User

from app.services.supplier import SupplierService


router = APIRouter()


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
    description="Returns list of brands waiting for connection approval."
)
def get_connection_requests(
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    return service.get_connection_requests(current_user)


@router.get(
    "/dashboard/tasks",
    response_model=List[ProductTaskItem],
    summary="Get Product Data Tasks",
    description="Returns list of sustainability data requests assigned to this supplier."
)
def get_product_tasks(
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    return service.get_product_tasks(current_user)


@router.get(
    "/directory/search",
    response_model=List[PublicTenantRead],
    summary="Search Supplier Directory",
    description="Find registered suppliers by name or handle."
)
def search_directory(
    q: str,
    service: SupplierService = Depends(get_supplier_service),
    current_user: User = Depends(get_current_user)
):
    return service.search_directory(q)


@router.get(
    "/",
    response_model=List[SupplierProfileRead],
    status_code=status.HTTP_200_OK,
    summary="List Supplier Profiles",
    description=(
        "Retrieve the address book of suppliers for the current Brand. "
        "Includes connection status and audit details (e.g., if an email invite was sent)."
    )
)
def list_suppliers(
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    """
    Fetches all supplier profiles owned by the current user's active Tenant.
    """
    return service.list_profiles(current_user)


@router.get(
    "/invitation/{token}",
    response_model=InviteDetails,
    summary="Verify Invitation Token",
    description="Used by the registration page to validate the token and pre-fill the user's email."
)
def verify_invitation(
    token: str,
    service: SupplierService = Depends(get_supplier_service)
):
    """
    Public endpoint (no auth required) to validate the link code.
    """
    return service.validate_invite_token(token)


@router.post(
    "/",
    response_model=SupplierProfileRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add or Invite a Supplier",
    description=(
        "Adds a new entry to the Supplier Address Book. \n\n"
        "**Modes of Operation:**\n"
        "1. **Connect by Handle:** Provide `public_handle` (e.g., 'pk-textiles') to request a B2B connection with an existing registered Manufacturer.\n"
        "2. **Invite by Email:** Provide `invite_email` to send a platform registration invitation to a new supplier.\n\n"
        "**Note:** You must provide exactly one of these identifiers along with a display `name`."
    )
)
def add_supplier(
    supplier_in: SupplierProfileCreate,
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    """
    Orchestrates the creation of a SupplierProfile and the linked TenantConnection.
    """
    new_profile = service.add_supplier(current_user, supplier_in)

    logger.info(
        f"Supplier '{new_profile.name}' added by User {current_user.id} "
        f"(Status: {new_profile.connection_status})"
    )

    return new_profile


@router.patch(
    "/{profile_id}",
    response_model=SupplierProfileRead,
    summary="Update Supplier Alias",
    description="Update the internal display name of a supplier."
)
def update_supplier(
    profile_id: uuid.UUID,
    data: SupplierProfileUpdate,
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    return service.update_profile(current_user, profile_id, data)


@router.delete(
    "/{profile_id}",
    status_code=status.HTTP_200_OK,
    summary="Disconnect or Remove Supplier",
    description=(
        "**Logic:**\n"
        "- If status is `PENDING`: Cancels the invite and removes the entry.\n"
        "- If status is `CONNECTED`: Breaks the connection (sets to Disconnected) but keeps the profile.\n"
        "- If status is `DISCONNECTED`: Removes the entry from the address book."
    )
)
def disconnect_supplier(
    profile_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    return service.disconnect_supplier(current_user, profile_id)


@router.get("/requests/incoming", response_model=List[ConnectionResponse])
def get_incoming_requests(
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    """
    Supplier Dashboard: See pending invites from Brands.
    """
    return service.list_incoming_requests(current_user)


@router.post("/requests/{connection_id}/respond")
def respond_to_invite(
    connection_id: uuid.UUID,
    payload: DecisionPayload,
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    """
    Supplier Dashboard: Accept or Decline a brand's invitation.
    """
    return service.respond_to_request(current_user, connection_id, payload.accept)


@router.post(
    "/{profile_id}/reinvite",
    response_model=SupplierProfileRead,
    summary="Resend Invitation",
    description="Resend an invite to a Pending or Declined supplier. Allows correcting the email and adding a note."
)
def resend_invitation(
    profile_id: uuid.UUID,
    data: SupplierReinvite,
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    return service.reinvite_supplier(current_user, profile_id, data)
