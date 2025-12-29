from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from app.core.dependencies import get_current_user, get_session
from app.services.certification import CertificationService
from app.models.certification import CertificationCreate, CertificationUpdate, CertificationRead
from app.db.schema import User

router = APIRouter()


def get_cert_service(session: Session = Depends(get_session)) -> CertificationService:
    return CertificationService(session)


@router.get(
    "/",
    response_model=List[CertificationRead],
    status_code=status.HTTP_200_OK,
    summary="List Certifications",
    description="Retrieve all certifications (System + Custom) available to you."
)
def list_certifications(
    q: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    service: CertificationService = Depends(get_cert_service)
):
    return service.list_certifications(current_user, query=q)


@router.post(
    "/",
    response_model=CertificationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create Custom Certification",
    description="Add a private certification type."
)
def create_certification(
    data: CertificationCreate,
    current_user: User = Depends(get_current_user),
    service: CertificationService = Depends(get_cert_service)
):
    return service.create_certification(current_user, data)


@router.patch(
    "/{cert_id}",
    response_model=CertificationRead,
    status_code=status.HTTP_200_OK,
    summary="Update Certification",
    description="Update a custom certification."
)
def update_certification(
    cert_id: UUID,
    data: CertificationUpdate,
    current_user: User = Depends(get_current_user),
    service: CertificationService = Depends(get_cert_service)
):
    return service.update_certification(current_user, cert_id, data)


@router.delete(
    "/{cert_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete Certification",
    description="Remove a custom certification."
)
def delete_certification(
    cert_id: UUID,
    current_user: User = Depends(get_current_user),
    service: CertificationService = Depends(get_cert_service)
):
    return service.delete_certification(current_user, cert_id)
