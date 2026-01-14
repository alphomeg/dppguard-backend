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
    ProductMediaReorder,
    ProductAssignmentRequest
)

router = APIRouter()

# ==============================================================================
# PRODUCT SHELL (Identity)
# ==============================================================================


@router.get("/", response_model=List[ProductRead])
def list_products(
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    List all products owned by the Brand. 
    Includes latest version info and main image URL.
    """
    return service.list_products(current_user)


@router.post("/", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(
    data: ProductCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Create a new Product Identity.
    - Creates the Product Shell.
    - Creates the Initial Version (v1) with the provided name (Draft state).
    - Uploads and attaches initial media if provided.
    """
    return service.create_product(current_user, data, background_tasks)


@router.get("/{product_id}", response_model=ProductRead)
def get_product_details(
    product_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Get a specific product with its full media gallery and latest version info.
    """
    return service.get_product(current_user, product_id)


@router.patch("/{product_id}/identity", response_model=ProductRead)
def update_product_identity(
    product_id: UUID,
    data: ProductIdentityUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Update Identity fields (Name, SKU, Lifecycle) only.
    Cannot edit Version/Technical data here.
    """
    # We return the full read model, requiring a re-fetch inside the service helper usually
    # or mapping the result manually.
    updated_product = service.update_product_identity(
        current_user, product_id, data, background_tasks)

    # Re-use get_product logic or construct simple response depending on performance needs
    # Here we just re-fetch to ensure response consistency
    return service.get_product(current_user, product_id)

# ==============================================================================
# MEDIA MANAGEMENT
# ==============================================================================


@router.post("/{product_id}/media", response_model=ProductMediaRead)
def add_product_media(
    product_id: UUID,
    data: ProductMediaAdd,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Upload a new image/video (Base64) and attach to product.
    If 'is_main' is True, unsets the previous main image.
    """
    return service.add_media(current_user, product_id, data, background_tasks)


@router.delete("/media/{media_id}", status_code=status.HTTP_200_OK)
def delete_product_media(
    media_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Remove a media asset. 
    If the Main image is deleted, the Product main_image_url cache becomes null.
    """
    return service.delete_media(current_user, media_id, background_tasks)


@router.patch("/{product_id}/media/{media_id}/main", status_code=status.HTTP_200_OK)
def set_main_media(
    product_id: UUID,
    media_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Set a specific existing media item as the Hero/Main image.
    """
    return service.set_main_media(current_user, product_id, media_id, background_tasks)


@router.post("/{product_id}/media/reorder", status_code=status.HTTP_200_OK)
def reorder_media(
    product_id: UUID,
    order_list: List[ProductMediaReorder],
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Bulk update the display_order of images.
    """
    return service.reorder_media(current_user, product_id, order_list, background_tasks)


@router.post("/{product_id}/assign", status_code=status.HTTP_201_CREATED)
def assign_product_to_supplier(
    product_id: UUID,
    data: ProductAssignmentRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Assigns a Product to a Supplier via their Profile.
    - If this is the first assignment, it converts the 'pending_version_name' into a real ProductVersion (v1).
    - If a version exists but is locked, it creates a new version (v2, v3...).
    - Sends a DataContributionRequest to the Supplier.
    """
    return service.assign_product(current_user, product_id, data, background_tasks)
