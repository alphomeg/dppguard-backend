from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, status, Query

from app.core.dependencies import (
    get_current_user,
    get_supplier_service,
)
from app.db.schema import User
from app.services.references.supplier import SupplierService

from app.models.supplier import SupplierRead, SupplierCreate, SupplierUpdate


router = APIRouter()


@router.post(
    "/suppliers",
    response_model=SupplierRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new Supplier",
    tags=["Suppliers"]
)
def create_supplier(
    payload: SupplierCreate,
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    """
    Registers a new supplier (Factory, Vendor, Mill) in the tenant's supply chain.
    """
    return service.create_supplier(user=current_user, data=payload)


@router.get(
    "/suppliers",
    response_model=List[SupplierRead],
    summary="List Suppliers",
    description="Returns list of suppliers strictly belonging to the current tenant.",
    tags=["Suppliers"]
)
def list_suppliers(
    country: Optional[str] = Query(None, description="Filter by Country"),
    search: Optional[str] = Query(None, description="Filter by Name"),
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    return service.list_suppliers(
        user=current_user,
        country_filter=country,
        search_query=search
    )


@router.get(
    "/suppliers/{supplier_id}",
    response_model=SupplierRead,
    summary="Get Supplier Details",
    tags=["Suppliers"]
)
def get_supplier(
    supplier_id: UUID,
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    return service.get_supplier(user=current_user, supplier_id=supplier_id)


@router.patch(
    "/suppliers/{supplier_id}",
    response_model=SupplierRead,
    summary="Update Supplier",
    tags=["Suppliers"]
)
def update_supplier(
    supplier_id: UUID,
    payload: SupplierUpdate,
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    """
    Updates supplier details (Address, Audit Rating, etc.).
    """
    return service.update_supplier(user=current_user, supplier_id=supplier_id, data=payload)


@router.delete(
    "/suppliers/{supplier_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete Supplier",
    tags=["Suppliers"]
)
def delete_supplier(
    supplier_id: UUID,
    current_user: User = Depends(get_current_user),
    service: SupplierService = Depends(get_supplier_service)
):
    """
    Removes a supplier from the registry.

    **Constraints:**
    - Cannot delete if the supplier is linked to an existing Product.
    """
    return service.delete_supplier(user=current_user, supplier_id=supplier_id)
