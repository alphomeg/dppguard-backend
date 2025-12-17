from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_current_user, get_dpp_service
from app.services.dpp import DPPService
from app.db.schema import User

from app.models.dpp import (
    DPPCreate, DPPRead, DPPUpdate, DPPFullDetailsRead,
    DPPEventCreate, DPPEventRead,
    DPPExtraDetailCreate, DPPExtraDetailRead, DPPPublicRead
)

router = APIRouter()


@router.get(
    "/public/{public_uid}",
    response_model=DPPPublicRead,
    summary="Fetch Public Passport",
    description="Public access point for QR codes. Only returns PUBLISHED passports.",
    tags=["Public"]
)
def get_public_passport(
    public_uid: str,
    service: DPPService = Depends(get_dpp_service)
):
    return service.get_public_passport(public_uid)


@router.get(
    "/",
    response_model=List[DPPRead],
    status_code=status.HTTP_200_OK,
    summary="List Passports",
    description="List all Digital Product Passports with associated Product details.",
    tags=["Digital Passport"]
)
def list_passports(
    current_user: User = Depends(get_current_user),
    service: DPPService = Depends(get_dpp_service)
):
    return service.list_passports(user=current_user)


@router.post(
    "/",
    response_model=DPPRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create Passport",
    description="Initializes a Digital Product Passport for an existing Product ID.",
    tags=["Digital Passport"]
)
def create_passport(
    payload: DPPCreate,
    current_user: User = Depends(get_current_user),
    service: DPPService = Depends(get_dpp_service)
):
    return service.create_passport(user=current_user, data=payload)


@router.get(
    "/{dpp_id}",
    response_model=DPPFullDetailsRead,
    summary="Get Full Passport",
    description="Returns passport metadata, audit timeline (events), and custom attributes.",
    tags=["Digital Passport"]
)
def get_passport_details(
    dpp_id: UUID,
    current_user: User = Depends(get_current_user),
    service: DPPService = Depends(get_dpp_service)
):
    return service.get_passport_full(user=current_user, dpp_id=dpp_id)


@router.patch(
    "/{dpp_id}",
    response_model=DPPRead,
    summary="Update Passport",
    tags=["Digital Passport"]
)
def update_passport(
    dpp_id: UUID,
    payload: DPPUpdate,
    current_user: User = Depends(get_current_user),
    service: DPPService = Depends(get_dpp_service)
):
    """
    Update status, target URL, or QR code location.
    """
    return service.update_passport(user=current_user, dpp_id=dpp_id, data=payload)


@router.post(
    "/{dpp_id}/events",
    response_model=DPPEventRead,
    status_code=status.HTTP_201_CREATED,
    summary="Log Event",
    tags=["Digital Passport - Events"]
)
def log_passport_event(
    dpp_id: UUID,
    payload: DPPEventCreate,
    current_user: User = Depends(get_current_user),
    service: DPPService = Depends(get_dpp_service)
):
    """
    Manually add an entry to the product journey (e.g. 'Quality Check Passed').
    """
    return service.log_event(user=current_user, dpp_id=dpp_id, data=payload)


@router.post(
    "/{dpp_id}/details",
    response_model=DPPExtraDetailRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add Custom Field",
    tags=["Digital Passport - Content"]
)
def add_custom_detail(
    dpp_id: UUID,
    payload: DPPExtraDetailCreate,
    current_user: User = Depends(get_current_user),
    service: DPPService = Depends(get_dpp_service)
):
    """
    Add a custom key-value pair to the passport (e.g. 'Warranty Video': 'http://...').
    """
    return service.add_extra_detail(user=current_user, dpp_id=dpp_id, data=payload)


@router.delete(
    "/{dpp_id}/details/{detail_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove Custom Field",
    tags=["Digital Passport - Content"]
)
def remove_custom_detail(
    dpp_id: UUID,
    detail_id: UUID,
    current_user: User = Depends(get_current_user),
    service: DPPService = Depends(get_dpp_service)
):
    service.delete_extra_detail(
        user=current_user, dpp_id=dpp_id, detail_id=detail_id)
    return


@router.delete(
    "/{dpp_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Passport",
    description="Deletes the passport and its history. The associated Product entity is NOT deleted.",
    tags=["Digital Passport"]
)
def delete_passport(
    dpp_id: UUID,
    current_user: User = Depends(get_current_user),
    service: DPPService = Depends(get_dpp_service)
):
    service.delete_passport(user=current_user, dpp_id=dpp_id)
    return
