# app/api/routes/materials.py
from fastapi import APIRouter, Depends, status
from typing import List, Optional
import uuid
from sqlmodel import Session

from app.db.schema import User
from app.core.dependencies import get_current_user, get_material_definition_service
from app.services.material_definition import MaterialDefinitionService
from app.models.material_definition import (
    MaterialDefinitionCreate,
    MaterialDefinitionUpdate,
    MaterialDefinitionRead
)

router = APIRouter()


@router.get(
    "/",
    response_model=List[MaterialDefinitionRead],
    summary="List Supplier Materials",
    description="Retrieve System Standards + Your Custom Materials. (Suppliers Only)"
)
def list_materials(
    q: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    service: MaterialDefinitionService = Depends(
        get_material_definition_service)
):
    return service.list_materials(current_user, query=q)


@router.post(
    "/",
    response_model=MaterialDefinitionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create Custom Material",
    description="Define a new material in your library. (Suppliers Only)"
)
def create_material(
    data: MaterialDefinitionCreate,
    current_user: User = Depends(get_current_user),
    service: MaterialDefinitionService = Depends(
        get_material_definition_service)
):
    return service.create_material(current_user, data)


@router.patch(
    "/{material_id}",
    response_model=MaterialDefinitionRead,
    summary="Update Material",
    description="Update a custom material. (Suppliers Only - Cannot edit System data)"
)
def update_material(
    material_id: uuid.UUID,
    data: MaterialDefinitionUpdate,
    current_user: User = Depends(get_current_user),
    service: MaterialDefinitionService = Depends(
        get_material_definition_service)
):
    return service.update_material(current_user, material_id, data)


@router.delete(
    "/{material_id}",
    summary="Delete Material",
    description="Remove a custom material. (Suppliers Only)"
)
def delete_material(
    material_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: MaterialDefinitionService = Depends(
        get_material_definition_service)
):
    return service.delete_material(current_user, material_id)
