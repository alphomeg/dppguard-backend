from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from app.core.dependencies import get_current_user, get_session
from app.services.material import MaterialService
from app.models.material import MaterialCreate, MaterialUpdate, MaterialRead
from app.db.schema import User

router = APIRouter()


def get_material_service(session: Session = Depends(get_session)) -> MaterialService:
    return MaterialService(session)


@router.get(
    "/",
    response_model=List[MaterialRead],
    status_code=status.HTTP_200_OK,
    summary="List Materials",
    description="Retrieve all materials available to your organization (System Standards + Your Custom Definitions)."
)
def list_materials(
    q: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    service: MaterialService = Depends(get_material_service)
):
    return service.list_materials(current_user, query=q)


@router.post(
    "/",
    response_model=MaterialRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create Custom Material",
    description="Add a new private material definition to your library."
)
def create_material(
    data: MaterialCreate,
    current_user: User = Depends(get_current_user),
    service: MaterialService = Depends(get_material_service)
):
    return service.create_material(current_user, data)


@router.patch(
    "/{material_id}",
    response_model=MaterialRead,
    status_code=status.HTTP_200_OK,
    summary="Update Material",
    description="Update a custom material. Note: System materials cannot be edited."
)
def update_material(
    material_id: UUID,
    data: MaterialUpdate,
    current_user: User = Depends(get_current_user),
    service: MaterialService = Depends(get_material_service)
):
    return service.update_material(current_user, material_id, data)


@router.delete(
    "/{material_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete Material",
    description="Remove a custom material. Will fail if the material is currently used in any Product data."
)
def delete_material(
    material_id: UUID,
    current_user: User = Depends(get_current_user),
    service: MaterialService = Depends(get_material_service)
):
    return service.delete_material(current_user, material_id)
