import uuid
from typing import List
from fastapi import APIRouter, Depends, status, BackgroundTasks, Query

from app.core.dependencies import get_current_user, get_tenant_connection_service
from app.db.schema import User
from app.services.tenant_connection import TenantConnectionService
from app.models.tenant_connection import (
    InviteDetails,
    PublicTenantRead,
    ConnectionReinvite,
    TenantConnectionRequestRespond
)
from app.models.supplier_profile import SupplierProfileRead

router = APIRouter()

# ==============================================================================
# PUBLIC / GENERIC ROUTES (Connection Agnostic)
# ==============================================================================


@router.get(
    "/invitations/{token}",
    response_model=InviteDetails,
    status_code=status.HTTP_200_OK,
    summary="Verify Invite Token",
    description="Public endpoint to validate an invite link. Returns the identity of the Tenant (Brand/Supplier) who sent it."
)
def verify_invitation(
    token: str,
    service: TenantConnectionService = Depends(get_tenant_connection_service)
):
    """
    Called by the 'Accept Invite' landing page. 
    Global scope: Works for Supplier invitations, Recycler invitations, etc.
    """
    return service.validate_invite_token(token)


@router.post(
    "/requests/{connection_id}/respond",
    status_code=status.HTTP_200_OK,
    summary="Respond to Request",
    description="Accept or Decline a connection request."
)
def respond_to_connection_request(
    connection_id: uuid.UUID,
    data: TenantConnectionRequestRespond,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: TenantConnectionService = Depends(get_tenant_connection_service)
):
    """
    Called by the Target (e.g., a Supplier) to accept/reject a Brand's request.
    Global scope: Handles any incoming B2B handshake.
    """
    return service.respond_to_request(current_user, connection_id, data.accept, background_tasks)


# ==============================================================================
# SUPPLIER-SPECIFIC SCOPE
# ==============================================================================

@router.get(
    "/directory/suppliers",
    response_model=List[PublicTenantRead],
    status_code=status.HTTP_200_OK,
    summary="Search Supplier Directory",
    description="Search specifically for existing Suppliers to connect with."
)
def search_supplier_directory(
    q: str = Query(..., min_length=2, description="Search by Name or Handle"),
    current_user: User = Depends(get_current_user),
    service: TenantConnectionService = Depends(get_tenant_connection_service)
):
    """
    Scoped Search: Only returns tenants with type='SUPPLIER'.
    """
    return service.search_directory(q)


@router.post(
    "/suppliers/{profile_id}/reinvite",
    response_model=SupplierProfileRead,
    status_code=status.HTTP_200_OK,
    summary="Resend Supplier Invitation",
    description="Triggers a re-send of the onboarding email to a specific Supplier in your Address Book."
)
def resend_supplier_invitation(
    profile_id: uuid.UUID,
    data: ConnectionReinvite,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: TenantConnectionService = Depends(get_tenant_connection_service)
):
    """
    Scoped Action: Operates specifically on a SupplierProfile ID.
    Updates the snapshot on the profile and the underlying connection.
    """
    return service.reinvite_supplier(current_user, profile_id, data, background_tasks)
