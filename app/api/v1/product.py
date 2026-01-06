from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, status

from app.db.schema import User
from app.core.dependencies import get_current_user, get_product_service, get_collab_service, get_brand_service
from app.services.brand import BrandService
from app.services.collaboration import CollaborationService
from app.services.product import ProductService
from app.models.data_contribution_request import AssignmentCreate
from app.models.product import ProductCreate, ProductRead, ProductDetailRead
from app.models.product import (
    VersionMetadataUpdate, VersionImpactUpdate,
    MaterialAdd, SupplierAdd, CertificationAdd
)


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
    description="Create a new Product shell (SKU, Name), initialize the first Draft Version, and save images."
)
def create_product(
    data: ProductCreate,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.create_product(current_user, data)


@router.get(
    "/{product_id}",
    response_model=ProductDetailRead,
)
def get_product_details(
    product_id: UUID,
    version_id: Optional[UUID] = None,  # NEW PARAM
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.get_product_details(current_user, product_id, version_id)

# 2. Update Impact


@router.patch("/{product_id}/versions/{version_id}/impact")
def update_impact(
    product_id: UUID, version_id: UUID,
    data: VersionImpactUpdate,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.update_version_impact(current_user, version_id, data)

# 3. Manage Materials


@router.post("/{product_id}/versions/{version_id}/materials")
def add_material(
    product_id: UUID, version_id: UUID, data: MaterialAdd,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.add_material(current_user, version_id, data)


@router.delete("/{product_id}/versions/{version_id}/materials/{item_id}")
def remove_material(
    product_id: UUID, version_id: UUID, item_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.remove_material(current_user, item_id)

# 4. Manage Suppliers


@router.post("/{product_id}/versions/{version_id}/suppliers")
def add_supplier(
    product_id: UUID, version_id: UUID, data: SupplierAdd,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.add_supplier(current_user, version_id, data)


@router.delete("/{product_id}/versions/{version_id}/suppliers/{item_id}")
def remove_supplier(
    product_id: UUID, version_id: UUID, item_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.remove_supplier(current_user, item_id)


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete Product",
    description="Permanently remove a product and all its versions."
)
def delete_product(
    product_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.delete_product(current_user, product_id)


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
