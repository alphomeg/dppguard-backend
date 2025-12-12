from typing import List, Optional
from uuid import UUID
from fastapi import HTTPException, status
from sqlmodel import Session, select, col, or_
from loguru import logger

from app.db.schema import (
    User, Material, ProductMaterialLink
)
from app.models.material import MaterialCreate, MaterialUpdate


class MaterialService:
    """
    Service layer for managing raw materials in the ESPR system.
    Handles CRUD operations with multi-tenancy enforcement and referential integrity checks.
    """

    def __init__(self, session: Session):
        """
        Initializes the service with a database session.

        Args:
            session (Session): The SQLModel database session.
        """
        self.session = session

    def create_material(self, user: User, data: MaterialCreate) -> Material:
        """
        Creates a new material record linked to the user's active tenant.

        Validates that the material code is unique before creation to prevent
        database constraints from raising unhandled exceptions.

        Args:
            user (User): The requesting user (must have a valid tenant_id).
            data (MaterialCreate): The payload containing material details (name, code, type).

        Returns:
            Material: The created material instance.

        Raises:
            HTTPException(409): If a material with the provided code already exists.
        """
        # Check for duplicates (Global or Tenant specific)
        existing = self.session.exec(
            select(Material).where(Material.code == data.code)
        ).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Material with code '{data.code}' already exists."
            )

        # Create and link to tenant
        material = Material(**data.model_dump(), tenant_id=user._tenant_id)
        self.session.add(material)
        self.session.commit()
        self.session.refresh(material)
        return material

    def list_materials(self, user: User, search_query: Optional[str] = None) -> List[Material]:
        """
        Retrieves a list of available materials.

        The result includes:
        1. Global System Materials (tenant_id is None).
        2. Custom Materials created by the user's tenant.

        Args:
            user (User): The requesting user.
            search_query (str, optional): A case-sensitive substring to filter materials by name.

        Returns:
            List[Material]: A list of matching material records.
        """
        query = select(Material).where(
            or_(Material.tenant_id == None, Material.tenant_id == user._tenant_id)
        )

        if search_query:
            query = query.where(col(Material.name).contains(search_query))

        return self.session.exec(query).all()

    def update_material(self, user: User, material_id: UUID, data: MaterialUpdate) -> Material:
        """
        Updates an existing material record.

        Enforces strict permission checks:
        1. Users cannot update Global/System materials.
        2. Users can only update materials belonging to their own tenant.
        3. If the 'code' is being changed, checks for uniqueness collisions.

        Args:
            user (User): The requesting user.
            material_id (UUID): The ID of the material to update.
            data (MaterialUpdate): The partial fields to update.

        Returns:
            Material: The updated material record.

        Raises:
            HTTPException(404): If the material does not exist.
            HTTPException(403): If trying to update a System material or another tenant's material.
            HTTPException(409): If the new 'code' is already taken by another material.
        """
        # 1. Fetch existing material
        material = self.session.exec(
            select(Material).where(Material.id == material_id)
        ).first()

        if not material:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Material not found."
            )

        # 2. Permission Check (Ownership)
        if material.tenant_id != user._tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot update System materials or materials from other workspaces."
            )

        # 3. Handle Code Uniqueness (if code is changing)
        if data.code is not None and data.code != material.code:
            existing_collision = self.session.exec(
                select(Material).where(Material.code == data.code)
            ).first()

            if existing_collision:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Material with code '{data.code}' already exists."
                )

        # 4. Apply Updates
        material_data = data.model_dump(exclude_unset=True)
        for key, value in material_data.items():
            setattr(material, key, value)

        self.session.add(material)
        self.session.commit()
        self.session.refresh(material)
        return material

    def delete_material(self, user: User, material_id: UUID):
        """
        Deletes a material record permanently.

        Performs checks to ensure Referential Integrity:
        1. Users cannot delete Global/System materials.
        2. Users cannot delete materials that are actively linked to Products.

        Args:
            user (User): The requesting user.
            material_id (UUID): The unique ID of the material.

        Returns:
            dict: A status message containing the deleted ID.

        Raises:
            HTTPException(404): If material is not found.
            HTTPException(403): If trying to delete a System material.
            HTTPException(409): If the material is in use by a Product.
        """
        # 1. Fetch
        material = self.session.exec(
            select(Material).where(Material.id == material_id)
        ).first()

        if not material:
            raise HTTPException(status_code=404, detail="Material not found")

        # 2. Ownership Check
        if material.tenant_id != user._tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot delete System materials or materials from other tenants."
            )

        # 3. Usage Check (Referential Integrity)
        # Check if this material is linked to any product via the pivot table
        usage_count = self.session.exec(
            select(ProductMaterialLink).where(
                ProductMaterialLink.material_id == material_id)
        ).first()

        if usage_count:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete this material because it is currently used in one or more products."
            )

        # 4. Delete
        self.session.delete(material)
        self.session.commit()
        return {"status": "deleted", "id": material_id}
