from fastapi import APIRouter, Depends, status, BackgroundTasks
from typing import List, Optional
import uuid

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
    status_code=status.HTTP_200_OK,
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
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: MaterialDefinitionService = Depends(
        get_material_definition_service)
):
    return service.create_material(current_user, data, background_tasks)


@router.patch(
    "/{material_id}",
    response_model=MaterialDefinitionRead,
    status_code=status.HTTP_200_OK,
    summary="Update Material",
    description="Update a custom material. (Suppliers Only - Cannot edit System data)"
)
def update_material(
    material_id: uuid.UUID,
    data: MaterialDefinitionUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: MaterialDefinitionService = Depends(
        get_material_definition_service)
):
    return service.update_material(current_user, material_id, data, background_tasks)


@router.delete(
    "/{material_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete Material",
    description="Remove a custom material. (Suppliers Only)"
)
def delete_material(
    material_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: MaterialDefinitionService = Depends(
        get_material_definition_service)
):
    return service.delete_material(current_user, material_id, background_tasks)
