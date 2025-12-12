from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, status, Query

from app.core.dependencies import (
    get_current_user,
    get_material_service,
)
from app.db.schema import User
from app.services.references.material import MaterialService

from app.models.material import MaterialRead, MaterialCreate, MaterialUpdate

router = APIRouter()


@router.post(
    "/",
    response_model=MaterialRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new Material",
    tags=["Materials"]
)
def create_material(
    payload: MaterialCreate,
    current_user: User = Depends(get_current_user),
    service: MaterialService = Depends(get_material_service)
):
    """
    Creates a new custom material for the tenant.

    - **Name**: Common commercial name.
    - **Code**: Unique ISO or ERP code (Must be unique).
    - **Type**: Natural, Synthetic, Blend, etc.
    """
    return service.create_material(user=current_user, data=payload)


@router.get(
    "/",
    response_model=List[MaterialRead],
    summary="List all Materials",
    description="Returns both Global (System) materials and Tenant-specific materials.",
    tags=["Materials"]
)
def list_materials(
    search: Optional[str] = Query(None, description="Filter by material name"),
    current_user: User = Depends(get_current_user),
    service: MaterialService = Depends(get_material_service)
):
    return service.list_materials(user=current_user, search_query=search)


@router.patch(
    "/{material_id}",
    response_model=MaterialRead,
    summary="Update a Material",
    tags=["Materials"]
)
def update_material(
    material_id: UUID,
    payload: MaterialUpdate,
    current_user: User = Depends(get_current_user),
    service: MaterialService = Depends(get_material_service)
):
    """
    Updates an existing custom material.

    **Constraints:**
    - You cannot update Global/System materials.
    - You cannot change the code to one that already exists.
    """
    return service.update_material(user=current_user, material_id=material_id, data=payload)


@router.delete(
    "/{material_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a Material",
    tags=["Materials"]
)
def delete_material(
    material_id: UUID,
    current_user: User = Depends(get_current_user),
    service: MaterialService = Depends(get_material_service)
):
    """
    Deletes a material permanently.

    **Constraints:**
    - Cannot delete if it is currently linked to a Product.
    - Cannot delete Global/System materials.
    """
    return service.delete_material(user=current_user, material_id=material_id)
