from typing import List, Optional
from uuid import UUID
from fastapi import HTTPException, status
from sqlmodel import Session, select, col, or_
from loguru import logger

from app.db.schema import (
    User, Certification, ProductCertificationLink
)
from app.models.certification import CertificationCreate, CertificationUpdate


class CertificationService:
    """
    Service layer for managing sustainability certifications (e.g., GOTS, Oeko-Tex).

    Handles CRUD operations with multi-tenancy enforcement.
    Certifications follow a Hybrid model:
    - Global/System Certifications: Visible to all, read-only for tenants.
    - Custom Certifications: Created by a tenant, visible and editable only by them.
    """

    def __init__(self, session: Session):
        """
        Initializes the service with a database session.

        Args:
            session (Session): The SQLModel database session.
        """
        self.session = session

    def create_certification(self, user: User, data: CertificationCreate) -> Certification:
        """
        Creates a new custom certification record for the user's tenant.

        Validates that the certification code is unique globally or within the tenant
        to prevent database constraint violations.

        Args:
            user (User): The requesting user.
            data (CertificationCreate): Payload containing cert details (name, code, issuer).

        Returns:
            Certification: The created certification instance.

        Raises:
            HTTPException(409): If a certification with the provided code already exists.
        """
        # 1. Check for duplicates (Global or Tenant specific)
        existing = self.session.exec(
            select(Certification).where(Certification.code == data.code)
        ).first()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Certification with code '{data.code}' already exists."
            )

        # 2. Create and link to tenant
        cert = Certification(**data.model_dump(), tenant_id=user._tenant_id)
        self.session.add(cert)
        self.session.commit()
        self.session.refresh(cert)
        return cert

    def list_certifications(self, user: User, search_query: Optional[str] = None) -> List[Certification]:
        """
        Retrieves a list of available certifications.

        The result includes:
        1. Global System Certifications (tenant_id is None).
        2. Custom Certifications created by the user's tenant.

        Args:
            user (User): The requesting user.
            search_query (str, optional): A case-sensitive substring to filter by name.

        Returns:
            List[Certification]: A list of matching certification records.
        """
        query = select(Certification).where(
            or_(
                Certification.tenant_id == None,
                Certification.tenant_id == user._tenant_id
            )
        )

        if search_query:
            query = query.where(col(Certification.name).contains(search_query))

        return self.session.exec(query).all()

    def update_certification(self, user: User, certification_id: UUID, data: CertificationUpdate) -> Certification:
        """
        Updates an existing certification record.

        Enforces strict permission checks:
        1. Users cannot update Global/System certifications.
        2. Users can only update certifications belonging to their own tenant.
        3. If the 'code' is being changed, checks for uniqueness collisions.

        Args:
            user (User): The requesting user.
            certification_id (UUID): The ID of the certification to update.
            data (CertificationUpdate): The partial fields to update.

        Returns:
            Certification: The updated certification record.

        Raises:
            HTTPException(404): If certification not found.
            HTTPException(403): If trying to update a System cert or another tenant's cert.
            HTTPException(409): If the new 'code' is already taken.
        """
        # 1. Fetch existing certification
        cert = self.session.exec(
            select(Certification).where(Certification.id == certification_id)
        ).first()

        if not cert:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Certification not found."
            )

        # 2. Permission Check (Ownership)
        if cert.tenant_id != user._tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot update System certifications or items from other workspaces."
            )

        # 3. Handle Code Uniqueness (if code is changing)
        if data.code is not None and data.code != cert.code:
            existing_collision = self.session.exec(
                select(Certification).where(Certification.code == data.code)
            ).first()

            if existing_collision:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Certification with code '{data.code}' already exists."
                )

        # 4. Apply Updates
        cert_data = data.model_dump(exclude_unset=True)
        for key, value in cert_data.items():
            setattr(cert, key, value)

        self.session.add(cert)
        self.session.commit()
        self.session.refresh(cert)
        return cert

    def delete_certification(self, user: User, certification_id: UUID):
        """
        Deletes a certification record permanently.

        Performs checks to ensure Referential Integrity:
        1. Users cannot delete Global/System certifications.
        2. Users cannot delete certifications that are actively linked to Products.

        Args:
            user (User): The requesting user.
            certification_id (UUID): The unique ID of the certification.

        Returns:
            dict: A status message containing the deleted ID.

        Raises:
            HTTPException(404): If certification not found.
            HTTPException(403): If trying to delete a System certification.
            HTTPException(409): If the certification is in use by a Product.
        """
        # 1. Fetch
        cert = self.session.exec(
            select(Certification).where(Certification.id == certification_id)
        ).first()

        if not cert:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Certification not found"
            )

        # 2. Ownership Check
        if cert.tenant_id != user._tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot delete System certifications."
            )

        # 3. Usage Check (Referential Integrity)
        # Check if this cert is linked to any product via the pivot table
        is_used = self.session.exec(
            select(ProductCertificationLink).where(
                ProductCertificationLink.certification_id == certification_id
            )
        ).first()

        if is_used:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete certification because it is assigned to one or more products."
            )

        # 4. Delete
        self.session.delete(cert)
        self.session.commit()
        return {"status": "deleted", "id": certification_id}
