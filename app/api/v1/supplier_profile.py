import uuid
from typing import List
from fastapi import APIRouter, Depends, status, BackgroundTasks

from app.core.dependencies import get_current_user, get_supplier_service
from app.db.schema import User
from app.services.supplier_profile import SupplierProfileService
from app.models.supplier_profile import (
    SupplierProfileCreate, SupplierProfileRead,
    SupplierProfileUpdate
)

router = APIRouter()


@router.get(
    "/",
    response_model=List[SupplierProfileRead],
    status_code=status.HTTP_200_OK,
    summary="List Address Book",
    description="Returns all suppliers configured by the current Brand, including connection status."
)
def list_suppliers(
    current_user: User = Depends(get_current_user),
    service: SupplierProfileService = Depends(get_supplier_service)
):
    return service.list_profiles(current_user)


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
    service: SupplierProfileService = Depends(get_supplier_service)
):
    return service.add_profile(current_user, data, background_tasks)


@router.patch(
    "/{profile_id}",
    response_model=SupplierProfileRead,
    status_code=status.HTTP_200_OK,
    summary="Update Profile",
    description="Update the alias or internal notes for a supplier."
)
def update_supplier(
    profile_id: uuid.UUID,
    data: SupplierProfileUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: SupplierProfileService = Depends(get_supplier_service)
):
    return service.update_profile(current_user, profile_id, data, background_tasks)


@router.delete(
    "/{profile_id}",
    status_code=status.HTTP_200_OK,
    summary="Disconnect Supplier",
    description="Removes a supplier. If invite is pending, it is cancelled. If connected, the link is severed."
)
def disconnect_supplier(
    profile_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: SupplierProfileService = Depends(get_supplier_service)
):
    return service.disconnect_supplier(current_user, profile_id, background_tasks)
