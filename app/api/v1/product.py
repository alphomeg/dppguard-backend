from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, status, Body

from app.db.schema import User
from app.core.dependencies import get_current_user, get_product_service, get_collab_service, get_brand_service
from app.services.brand import BrandService
from app.services.collaboration import CollaborationService
from app.services.product import ProductService
from app.models.data_contribution_request import AssignmentCreate
from app.models.product import (
    ProductCreate, ProductRead, ProductDetailRead,
    VersionMetadataUpdate, VersionImpactUpdate,
    MaterialAdd, MaterialUpdate,
    SupplierAdd, SupplierUpdate,
    CertificationAdd, CertificationUpdate,
    ProductImageAdd
)

router = APIRouter()

# --- BASIC CRUD ---


@router.get("/", response_model=List[ProductRead])
def list_products(
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.list_products(current_user)


@router.post("/", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(
    data: ProductCreate,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.create_product(current_user, data)


@router.get("/{product_id}", response_model=ProductDetailRead)
def get_product_details(
    product_id: UUID,
    version_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.get_product_details(current_user, product_id, version_id)


@router.delete("/{product_id}")
def delete_product(
    product_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.delete_product(current_user, product_id)

# --- 1. OVERVIEW & METADATA EDITING ---


@router.patch("/{product_id}/versions/{version_id}/metadata")
def update_product_overview(
    product_id: UUID, version_id: UUID,
    data: VersionMetadataUpdate,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """Updates Name, Description, Category, GTIN, Version Name."""
    return service.update_version_metadata(current_user, version_id, data)

# --- 2. IMAGE MANAGEMENT ---


@router.post("/{product_id}/versions/{version_id}/media")
def add_product_image(
    product_id: UUID, version_id: UUID,
    data: ProductImageAdd,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.add_image(current_user, version_id, data)


@router.delete("/{product_id}/versions/{version_id}/media/{media_id}")
def delete_product_image(
    product_id: UUID, version_id: UUID, media_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.delete_image(current_user, version_id, media_id)


@router.patch("/{product_id}/versions/{version_id}/media/{media_id}/set-main")
def set_main_image(
    product_id: UUID, version_id: UUID, media_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.set_main_image(current_user, version_id, media_id)


# --- 3. MATERIALS EDITING ---

@router.post("/{product_id}/versions/{version_id}/materials")
def add_material(
    product_id: UUID, version_id: UUID, data: MaterialAdd,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.add_material(current_user, version_id, data)


@router.patch("/{product_id}/versions/{version_id}/materials/{item_id}")
def update_material(
    product_id: UUID, version_id: UUID, item_id: UUID,
    data: MaterialUpdate,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """Updates percentage, origin, or name of an existing material row."""
    return service.update_material(current_user, version_id, item_id, data)


@router.delete("/{product_id}/versions/{version_id}/materials/{item_id}")
def remove_material(
    product_id: UUID, version_id: UUID, item_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.remove_material(current_user, version_id, item_id)


# --- 4. SUPPLY CHAIN EDITING ---

@router.post("/{product_id}/versions/{version_id}/suppliers")
def add_supplier(
    product_id: UUID, version_id: UUID, data: SupplierAdd,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.add_supplier(current_user, version_id, data)


@router.patch("/{product_id}/versions/{version_id}/suppliers/{item_id}")
def update_supplier(
    product_id: UUID, version_id: UUID, item_id: UUID,
    data: SupplierUpdate,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """Updates role, name, or country of an existing supply node."""
    return service.update_supplier(current_user, version_id, item_id, data)


@router.delete("/{product_id}/versions/{version_id}/suppliers/{item_id}")
def remove_supplier(
    product_id: UUID, version_id: UUID, item_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.remove_supplier(current_user, version_id, item_id)


# --- 5. IMPACT EDITING ---

@router.patch("/{product_id}/versions/{version_id}/impact")
def update_impact(
    product_id: UUID, version_id: UUID,
    data: VersionImpactUpdate,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.update_version_impact(current_user, version_id, data)


# --- 6. CERTIFICATIONS EDITING ---

@router.post("/{product_id}/versions/{version_id}/certifications")
def add_certification(
    product_id: UUID, version_id: UUID, data: CertificationAdd,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.add_certification(current_user, version_id, data)


@router.patch("/{product_id}/versions/{version_id}/certifications/{item_id}")
def update_certification(
    product_id: UUID, version_id: UUID, item_id: UUID,
    data: CertificationUpdate,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """Updates expiry date or document URL."""
    return service.update_certification(current_user, version_id, item_id, data)


@router.delete("/{product_id}/versions/{version_id}/certifications/{item_id}")
def remove_certification(
    product_id: UUID, version_id: UUID, item_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    return service.remove_certification(current_user, version_id, item_id)


# --- COLLABORATION / SOURCING (Existing) ---

@router.post("/{product_id}/assign", status_code=status.HTTP_201_CREATED)
def assign_supplier(
    product_id: UUID,
    data: AssignmentCreate,
    current_user: User = Depends(get_current_user),
    service: CollaborationService = Depends(get_collab_service)
):
    return service.assign_supplier(current_user, product_id, data)


@router.get("/reviews/pending")
def get_pending_reviews(
    current_user: User = Depends(get_current_user),
    service: BrandService = Depends(get_brand_service)
):
    return service.get_pending_reviews(current_user)
