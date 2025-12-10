from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, status, Query

from app.core.dependencies import (
    get_current_user,
    get_certification_service,
)
from app.db.schema import User
from app.services.references.certification import CertificationService

from app.models.certification import CertificationRead, CertificationCreate, CertificationUpdate


router = APIRouter()


@router.post(
    "/certifications",
    response_model=CertificationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create Certification",
    tags=["Certifications"]
)
def create_certification(
    payload: CertificationCreate,
    current_user: User = Depends(get_current_user),
    service: CertificationService = Depends(get_certification_service)
):
    """
    Creates a new custom certification standard.
    """
    return service.create_certification(user=current_user, data=payload)


@router.get(
    "/certifications",
    response_model=List[CertificationRead],
    summary="List Certifications",
    description="Returns both Global (System) certifications and Tenant-specific ones.",
    tags=["Certifications"]
)
def list_certifications(
    search: Optional[str] = Query(None, description="Filter by name"),
    current_user: User = Depends(get_current_user),
    service: CertificationService = Depends(get_certification_service)
):
    return service.list_certifications(user=current_user, search_query=search)


@router.patch(
    "/certifications/{certification_id}",
    response_model=CertificationRead,
    summary="Update Certification",
    tags=["Certifications"]
)
def update_certification(
    certification_id: UUID,
    payload: CertificationUpdate,
    current_user: User = Depends(get_current_user),
    service: CertificationService = Depends(get_certification_service)
):
    """
    Updates a custom certification.

    **Constraints:**
    - Cannot update System/Global certifications.
    - Code must remain unique.
    """
    return service.update_certification(user=current_user, certification_id=certification_id, data=payload)


@router.delete(
    "/certifications/{certification_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete Certification",
    tags=["Certifications"]
)
def delete_certification(
    certification_id: UUID,
    current_user: User = Depends(get_current_user),
    service: CertificationService = Depends(get_certification_service)
):
    """
    Deletes a certification permanently.

    **Constraints:**
    - Cannot delete if currently assigned to a Product.
    - Cannot delete System/Global certifications.
    """
    return service.delete_certification(user=current_user, certification_id=certification_id)
