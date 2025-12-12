from typing import List, Optional
from uuid import UUID
from fastapi import HTTPException, status
from sqlmodel import Session, select, col
from loguru import logger

from app.db.schema import (
    User, Supplier, ProductSupplierLink
)
from app.models.supplier import SupplierCreate, SupplierUpdate


class SupplierService:
    """
    Service layer for managing supply chain actors (Factories, Vendors).

    Unlike Materials, Suppliers are strictly tenant-scoped (Private).
    This service handles CRUD operations with strict isolation and usage checks.
    """

    def __init__(self, session: Session):
        """
        Initializes the service with a database session.

        Args:
            session (Session): The SQLModel database session.
        """
        self.session = session

    def create_supplier(self, user: User, data: SupplierCreate) -> Supplier:
        """
        Registers a new supplier within the user's active tenant.

        Args:
            user (User): The requesting user.
            data (SupplierCreate): Payload containing supplier details (name, country, address).

        Returns:
            Supplier: The created supplier record.
        """
        # Check for duplicates (Global or Tenant specific)
        existing = self.session.exec(
            select(Supplier).where(Supplier.name == data.name)
        ).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Supplier with name '{data.name}' already exists."
            )

        supplier = Supplier(
            **data.model_dump(),
            tenant_id=user._tenant_id
        )

        self.session.add(supplier)
        self.session.commit()
        self.session.refresh(supplier)
        return supplier

    def list_suppliers(self, user: User, country_filter: Optional[str] = None, search_query: Optional[str] = None) -> List[Supplier]:
        """
        Retrieves a list of suppliers belonging to the user's tenant.

        Args:
            user (User): The requesting user.
            country_filter (str, optional): Exact match filter for 'location_country'.
            search_query (str, optional): Case-sensitive substring filter for supplier name.

        Returns:
            List[Supplier]: A list of matching supplier records.
        """
        # Strict isolation: Only show suppliers for this tenant
        query = select(Supplier).where(Supplier.tenant_id == user._tenant_id)

        if country_filter:
            query = query.where(Supplier.location_country == country_filter)

        if search_query:
            query = query.where(col(Supplier.name).contains(search_query))

        return self.session.exec(query).all()

    def get_supplier(self, user: User, supplier_id: UUID) -> Supplier:
        """
        Retrieves a single supplier by ID, ensuring tenant access rights.

        Args:
            user (User): The requesting user.
            supplier_id (UUID): The ID of the supplier.

        Returns:
            Supplier: The found supplier.

        Raises:
            HTTPException(404): If not found or belongs to another tenant.
        """
        supplier = self.session.exec(
            select(Supplier).where(
                Supplier.id == supplier_id,
                Supplier.tenant_id == user._tenant_id
            )
        ).first()

        if not supplier:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Supplier not found."
            )

        return supplier

    def update_supplier(self, user: User, supplier_id: UUID, data: SupplierUpdate) -> Supplier:
        """
        Updates an existing supplier record.

        Args:
            user (User): The requesting user.
            supplier_id (UUID): The unique ID of the supplier.
            data (SupplierUpdate): Partial fields to update (name, address, rating).

        Returns:
            Supplier: The updated supplier record.

        Raises:
            HTTPException(404): If supplier is not found or access is denied.
        """
        # 1. Fetch & Permission Check combined (by including tenant_id in where)
        supplier = self.session.exec(
            select(Supplier).where(
                Supplier.id == supplier_id,
                Supplier.tenant_id == user._tenant_id
            )
        ).first()

        if not supplier:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Supplier not found."
            )

        # 2. Handle Code Uniqueness (if name is changing)
        if data.name is not None and data.name != supplier.name:
            existing_collision = self.session.exec(
                select(Supplier).where(supplier.name == data.name)
            ).first()

            if existing_collision:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Supplier with name '{data.name}' already exists."
                )

        # 3. Apply Updates
        supplier_data = data.model_dump(exclude_unset=True)
        for key, value in supplier_data.items():
            setattr(supplier, key, value)

        self.session.add(supplier)
        self.session.commit()
        self.session.refresh(supplier)
        return supplier

    def delete_supplier(self, user: User, supplier_id: UUID):
        """
        Deletes a supplier record permanently.

        Performs strict Referential Integrity checks:
        1. Ensures the supplier belongs to the current tenant.
        2. Ensures the supplier is not linked to any existing Products.

        Args:
            user (User): The requesting user.
            supplier_id (UUID): The unique ID of the supplier.

        Returns:
            dict: Status message.

        Raises:
            HTTPException(404): If supplier is not found.
            HTTPException(409): If the supplier is currently part of a product's supply chain.
        """
        # 1. Fetch & Permission Check
        supplier = self.session.exec(
            select(Supplier).where(
                Supplier.id == supplier_id,
                Supplier.tenant_id == user._tenant_id
            )
        ).first()

        if not supplier:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Supplier not found."
            )

        # 2. Usage Check (Referential Integrity)
        # Check if this supplier is used in any ProductSupplierLink
        is_used = self.session.exec(
            select(ProductSupplierLink).where(
                ProductSupplierLink.supplier_id == supplier_id
            )
        ).first()

        if is_used:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete supplier because they are linked to existing products."
            )

        # 3. Delete
        self.session.delete(supplier)
        self.session.commit()
        return {"status": "deleted", "id": supplier_id}
