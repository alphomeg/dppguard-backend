from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, status, Query, BackgroundTasks

from app.core.dependencies import get_current_user, get_certificate_definition_service
from app.services.certificate_definition import CertificateDefinitionService
from app.models.certificate_definition import (
    CertificateDefinitionCreate,
    CertificateDefinitionUpdate,
    CertificateDefinitionRead
)
from app.db.schema import User, CertificateCategory

router = APIRouter()


@router.get(
    "/",
    response_model=List[CertificateDefinitionRead],
    status_code=status.HTTP_200_OK,
    summary="List Certificate Definitions",
    description="Retrieve all certificate standards (System Global + Tenant Custom) available to the current user. Supports filtering by name and category."
)
def list_certificate_definitions(
    q: Optional[str] = Query(None, description="Search by Name or Issuer"),
    category: Optional[CertificateCategory] = Query(
        None, description="Filter by legal category (e.g., environmental, social)"),
    current_user: User = Depends(get_current_user),
    service: CertificateDefinitionService = Depends(
        get_certificate_definition_service)
):
    return service.list_definitions(current_user, query=q, category=category)


@router.post(
    "/",
    response_model=CertificateDefinitionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create Custom Definition",
    description="Define a new internal certificate standard. Restricted to Suppliers."
)
def create_certificate_definition(
    data: CertificateDefinitionCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: CertificateDefinitionService = Depends(
        get_certificate_definition_service)
):
    return service.create_definition(current_user, data, background_tasks)


@router.patch(
    "/{definition_id}",
    response_model=CertificateDefinitionRead,
    status_code=status.HTTP_200_OK,
    summary="Update Definition",
    description="Update a custom certificate definition. System definitions cannot be modified."
)
def update_certificate_definition(
    definition_id: UUID,
    data: CertificateDefinitionUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: CertificateDefinitionService = Depends(
        get_certificate_definition_service)
):
    return service.update_definition(current_user, definition_id, data, background_tasks)


@router.delete(
    "/{definition_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete Definition",
    description="Remove a custom certificate definition. Fails if the definition is currently in use by any Product Versions."
)
def delete_certificate_definition(
    definition_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: CertificateDefinitionService = Depends(
        get_certificate_definition_service)
):
    return service.delete_definition(current_user, definition_id, background_tasks)
