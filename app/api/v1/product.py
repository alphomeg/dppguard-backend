from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, status, BackgroundTasks

from app.db.schema import User
from app.core.dependencies import get_current_user, get_product_service
from app.services.product import ProductService
from app.models.product import (
    ProductCreate,
    ProductRead,
    ProductIdentityUpdate,
    ProductMediaAdd,
    ProductMediaRead,
    ProductMediaReorder
)

router = APIRouter()

# ==============================================================================
# PRODUCT SHELL (Identity)
# ==============================================================================


@router.get(
    "/",
    response_model=List[ProductRead],
    status_code=status.HTTP_200_OK,
    summary="List Products",
    description="List all products owned by the Brand. Includes latest version info and main image URL."
)
def list_products(
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.list_products(current_user)


@router.post(
    "/",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create Product",
    description="Create a new Product Identity. Creates the Shell, the Initial Version (v1), and handles initial media upload."
)
def create_product(
    data: ProductCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.create_product(current_user, data, background_tasks)


@router.get(
    "/{product_id}",
    response_model=ProductRead,
    status_code=status.HTTP_200_OK,
    summary="Get Product Details",
    description="Get a specific product with its full media gallery and latest version info."
)
def get_product_details(
    product_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.get_product(current_user, product_id)


@router.patch(
    "/{product_id}/identity",
    response_model=ProductRead,
    status_code=status.HTTP_200_OK,
    summary="Update Product Identity",
    description="Update Identity fields (Name, SKU, Lifecycle) only. Cannot edit Version/Technical data here."
)
def update_product_identity(
    product_id: UUID,
    data: ProductIdentityUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    service.update_product_identity(
        current_user, product_id, data, background_tasks)

    # Re-fetch to ensure response consistency
    return service.get_product(current_user, product_id)


# ==============================================================================
# MEDIA MANAGEMENT
# ==============================================================================


@router.post(
    "/{product_id}/media",
    response_model=ProductMediaRead,
    status_code=status.HTTP_200_OK,
    summary="Add Product Media",
    description="Upload a new image/video (Base64) and attach to product. If 'is_main' is True, unsets the previous main image."
)
def add_product_media(
    product_id: UUID,
    data: ProductMediaAdd,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.add_media(current_user, product_id, data, background_tasks)


@router.delete(
    "/media/{media_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete Media",
    description="Remove a media asset. If the Main image is deleted, the Product cache is updated."
)
def delete_product_media(
    media_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.delete_media(current_user, media_id, background_tasks)


@router.patch(
    "/{product_id}/media/{media_id}/main",
    status_code=status.HTTP_200_OK,
    summary="Set Main Image",
    description="Set a specific existing media item as the Hero/Main image."
)
def set_main_media(
    product_id: UUID,
    media_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.set_main_media(current_user, product_id, media_id, background_tasks)


@router.post(
    "/{product_id}/media/reorder",
    status_code=status.HTTP_200_OK,
    summary="Reorder Media",
    description="Bulk update the display_order of images."
)
def reorder_media(
    product_id: UUID,
    order_list: List[ProductMediaReorder],
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.reorder_media(current_user, product_id, order_list, background_tasks)
