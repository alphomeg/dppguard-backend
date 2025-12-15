from uuid import UUID
from typing_extensions import List
from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_current_user, get_product_service
from app.db.schema import User
from app.services.product import ProductService

from app.models.product import (
    ProductCreate,
    ProductRead,
    ProductUpdate,
    ProductFullDetailsRead
)
from app.models.product_durability import (
    ProductDurabilityUpdate,
    ProductDurabilityRead
)
from app.models.product_environmental import (
    ProductEnvironmentalUpdate,
    ProductEnvironmentalRead
)
from app.models.product_material import ProductMaterialLinkCreate
from app.models.product_supplier import ProductSupplierLinkCreate
from app.models.product_certification import ProductCertificationLinkCreate
from app.models.product_spare_part import SparePartCreate, SparePartRead

router = APIRouter()


@router.get(
    "/",
    response_model=List[ProductRead],
    summary="List Products",
    tags=["Products"]
)
def list_products(
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Retrieve a paginated list of products for the current tenant.
    """
    return service.list_products(user=current_user)


@router.post(
    "/",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create Product Shell",
    tags=["Products"]
)
def create_product(
    payload: ProductCreate,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Creates the basic identity of a clothing product (SKU, Name, Batch).
    Does not include materials or environmental data yet.
    """
    return service.create_product(user=current_user, data=payload)


@router.get(
    "/{product_id}",
    response_model=ProductFullDetailsRead,
    summary="Get Digital Product Passport (DPP)",
    description="Returns the full aggregated view: Details + Materials + Suppliers + Certs + Footprint.",
    tags=["Products"]
)
def get_product_dpp(
    product_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Fetches the deep-loaded product object.
    """
    return service.get_product_full(user=current_user, product_id=product_id)


@router.patch(
    "/{product_id}",
    response_model=ProductRead,
    summary="Update Basic Info",
    tags=["Products"]
)
def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Updates basic fields like Name, Brand, or Manufacturing Country.
    """
    return service.update_product(user=current_user, product_id=product_id, data=payload)


@router.put(
    "/{product_id}/durability",
    response_model=ProductDurabilityRead,
    summary="Upsert Durability Data",
    tags=["Products - ESPR"]
)
def upsert_durability(
    product_id: UUID,
    payload: ProductDurabilityUpdate,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Sets the circularity metrics (pilling, repairability score).
    Creates the record if it doesn't exist, updates it if it does.
    """
    return service.upsert_durability(user=current_user, product_id=product_id, data=payload)


@router.put(
    "/{product_id}/environmental",
    response_model=ProductEnvironmentalRead,
    summary="Upsert Environmental Data",
    tags=["Products - ESPR"]
)
def upsert_environmental(
    product_id: UUID,
    payload: ProductEnvironmentalUpdate,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Sets the PEF metrics (Carbon footprint, water usage, microplastics).
    Creates the record if it doesn't exist, updates it if it does.
    """
    return service.upsert_environmental(user=current_user, product_id=product_id, data=payload)


@router.post(
    "/{product_id}/materials",
    status_code=status.HTTP_201_CREATED,
    summary="Add Material Composition",
    tags=["Products - Composition"]
)
def add_product_material(
    product_id: UUID,
    payload: ProductMaterialLinkCreate,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Links a raw material (e.g. Cotton) to this product with a percentage.
    If the link exists, it updates the percentage/origin.
    """
    return service.add_material_link(user=current_user, product_id=product_id, data=payload)


@router.post(
    "/{product_id}/suppliers",
    status_code=status.HTTP_201_CREATED,
    summary="Add Supplier",
    tags=["Products - Supply Chain"]
)
def add_product_supplier(
    product_id: UUID,
    payload: ProductSupplierLinkCreate,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Links a supplier (e.g. Tier 1 Assembly) to this product.
    """
    return service.add_supplier_link(user=current_user, product_id=product_id, data=payload)


@router.post(
    "/{product_id}/certifications",
    status_code=status.HTTP_201_CREATED,
    summary="Add Certification",
    tags=["Products - Compliance"]
)
def add_product_certification(
    product_id: UUID,
    payload: ProductCertificationLinkCreate,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Links a compliance certificate to this product.
    """
    return service.add_certification_link(user=current_user, product_id=product_id, data=payload)


@router.post(
    "/{product_id}/parts",
    response_model=SparePartRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register Spare Part",
    tags=["Products - Repairability"]
)
def create_spare_part(
    product_id: UUID,
    payload: SparePartCreate,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Registers a spare part available for this product model.
    """
    return service.add_spare_part(user=current_user, product_id=product_id, data=payload)


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Product",
    tags=["Products"]
)
def delete_product(
    product_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Deletes a product. 
    This will cascade delete related links (materials, suppliers) and extensions (durability, environmental)
    depending on your database cascade settings.
    """
    service.delete_product(user=current_user, product_id=product_id)
    return


@router.delete(
    "/{product_id}/materials/{material_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove Material",
    tags=["Products - Composition"]
)
def remove_product_material(
    product_id: UUID,
    material_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Removes a raw material from the product's composition.
    """
    service.remove_material_link(
        user=current_user, product_id=product_id, material_id=material_id)
    return


@router.delete(
    "/{product_id}/suppliers/{supplier_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove Supplier",
    tags=["Products - Supply Chain"]
)
def remove_product_supplier(
    product_id: UUID,
    supplier_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Removes a supplier (and all their roles) from this product.
    """
    service.remove_supplier_link(
        user=current_user, product_id=product_id, supplier_id=supplier_id)
    return


@router.delete(
    "/{product_id}/certifications/{certification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove Certification",
    tags=["Products - Compliance"]
)
def remove_product_certification(
    product_id: UUID,
    certification_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Unlinks a compliance certificate from the product.
    """
    service.remove_certification_link(
        user=current_user, product_id=product_id, certification_id=certification_id)
    return


@router.delete(
    "/{product_id}/parts/{part_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Spare Part",
    tags=["Products - Repairability"]
)
def delete_spare_part(
    product_id: UUID,
    part_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProductService = Depends(get_product_service)
):
    """
    Permanently deletes a spare part entry for this product.
    """
    service.remove_spare_part(
        user=current_user, product_id=product_id, part_id=part_id)
    return
