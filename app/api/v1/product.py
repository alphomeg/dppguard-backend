from uuid import UUID
from fastapi import APIRouter, Depends, status
from typing import List

from app.core.dependencies import get_current_user, get_product_service, get_collab_service, get_brand_service
from app.db.schema import User
from app.models.product import ProductCreate, ProductRead
from app.models.data_contribution_request import AssignmentCreate
from app.services.product import ProductService
from app.services.collaboration import CollaborationService
from app.services.brand import BrandService

router = APIRouter()


@router.get(
    "/",
    response_model=List[ProductRead],
    status_code=status.HTTP_200_OK,
    summary="List Products",
    description="Retrieve all products for the current Brand, including their latest version status."
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
    description="Create a new Product shell (SKU, Name) and initialize the first Draft Version."
)
def create_product(
    data: ProductCreate,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.create_product(current_user, data)


@router.post(
    "/{product_id}/assign",
    status_code=status.HTTP_201_CREATED,
    summary="Assign Supplier",
    description="Assign a Supplier from your address book to provide data for this product."
)
def assign_supplier(
    product_id: UUID,
    data: AssignmentCreate,
    current_user: User = Depends(get_current_user),
    service: CollaborationService = Depends(get_collab_service)
):
    # We use CollaborationService here because this action creates a 'DataContributionRequest'
    return service.assign_supplier(current_user, product_id, data)


@router.get(
    "/reviews/pending",
    status_code=status.HTTP_200_OK,
    summary="Get Pending Reviews",
    description="List of submissions from suppliers waiting for approval."
)
def get_pending_reviews(
    current_user: User = Depends(get_current_user),
    service: BrandService = Depends(get_brand_service)
):
    return service.get_pending_reviews(current_user)
