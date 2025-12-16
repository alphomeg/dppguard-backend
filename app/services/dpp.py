import uuid
from typing import List, Optional
from fastapi import HTTPException, status
from sqlmodel import Session, select
from sqlalchemy.orm import selectinload

from app.utils.qr import generate_and_save_qr
from app.core.config import settings
from app.db.schema import (
    User, Product, DigitalProductPassport, DPPEvent, DPPExtraDetail
)
from app.models.dpp import (
    DPPCreate, DPPUpdate, DPPFullDetailsRead,
    DPPEventCreate, DPPExtraDetailCreate
)


class DPPService:
    def __init__(self, session: Session):
        self.session = session

    def list_passports(self, user: User) -> List[DigitalProductPassport]:
        """
        List all passports belonging to the user's tenant.
        Includes eager loading of Product details for the UI.
        """
        query = (
            select(DigitalProductPassport)
            .where(DigitalProductPassport.tenant_id == user._tenant_id)
            # Load product data
            .options(selectinload(DigitalProductPassport.product))
            .order_by(DigitalProductPassport.created_at.desc())
        )
        return self.session.exec(query).all()

    def get_passport_by_id(self, user: User, dpp_id: uuid.UUID) -> DigitalProductPassport:
        """
        Retrieves a passport ensuring it belongs to the current tenant.
        """
        dpp = self.session.exec(
            select(DigitalProductPassport).where(
                DigitalProductPassport.id == dpp_id,
                DigitalProductPassport.tenant_id == user._tenant_id
            )
        ).first()

        if not dpp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Digital Product Passport not found or access denied."
            )
        return dpp

    def create_passport(self, user: User, data: DPPCreate) -> DigitalProductPassport:
        # 1. Verify Product ownership
        # We must still ensure the target product belongs to this tenant
        product = self.session.exec(
            select(Product).where(
                Product.id == data.product_id,
                Product.tenant_id == user._tenant_id
            )
        ).first()

        if not product:
            raise HTTPException(status_code=404, detail="Product not found.")

        # 2. Check if Passport already exists (1:1 Restriction)
        existing_dpp = self.session.exec(
            select(DigitalProductPassport).where(
                DigitalProductPassport.product_id == data.product_id
            )
        ).first()

        if existing_dpp:
            raise HTTPException(
                status_code=409,
                detail="This product already has a Digital Passport."
            )

        # 3. Generate Public UID if not provided
        public_uid = data.public_uid or str(uuid.uuid4())

        # 4. Generate Backend Fields (Target URL & QR)
        target_url = f"{settings.public_url}/{public_uid}"
        qr_code_url = generate_and_save_qr(target_url, public_uid)

        # 4. Create with Tenant ID
        dpp = DigitalProductPassport(
            tenant_id=user._tenant_id,
            product_id=data.product_id,
            status=data.status,
            public_uid=public_uid,
            target_url=target_url,
            qr_code_url=qr_code_url
        )

        self.session.add(dpp)
        self.session.commit()
        self.session.refresh(dpp)
        return dpp

    def get_passport_full(self, user: User, dpp_id: uuid.UUID) -> DPPFullDetailsRead:
        """
        Fetches the Passport with Events and Extra Details.
        """
        # Validate ownership via ID check first (or combine into one query)
        query = (
            select(DigitalProductPassport)
            .where(
                DigitalProductPassport.id == dpp_id,
                DigitalProductPassport.tenant_id == user._tenant_id
            )
            .options(
                selectinload(DigitalProductPassport.events),
                selectinload(DigitalProductPassport.extra_details)
            )
        )

        dpp = self.session.exec(query).first()
        if not dpp:
            raise HTTPException(status_code=404, detail="Passport not found")

        return DPPFullDetailsRead.model_validate(dpp)

    def update_passport(self, user: User, dpp_id: uuid.UUID, data: DPPUpdate) -> DigitalProductPassport:
        dpp = self.get_passport_by_id(user, dpp_id)

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(dpp, key, value)

        self.session.add(dpp)
        self.session.commit()
        self.session.refresh(dpp)
        return dpp

    def log_event(self, user: User, dpp_id: uuid.UUID, data: DPPEventCreate) -> DPPEvent:
        """
        Manually adds an audit log entry.
        """
        # Ensure parent exists and is owned by tenant
        self.get_passport_by_id(user, dpp_id)

        event = DPPEvent(
            tenant_id=user._tenant_id,  # Set Tenant ID
            dpp_id=dpp_id,
            actor_id=user.id,
            **data.model_dump()
        )
        self.session.add(event)
        self.session.commit()
        self.session.refresh(event)
        return event

    def add_extra_detail(self, user: User, dpp_id: uuid.UUID, data: DPPExtraDetailCreate):
        """
        Adds a custom key-value pair.
        """
        self.get_passport_by_id(user, dpp_id)

        detail = DPPExtraDetail(
            tenant_id=user._tenant_id,  # Set Tenant ID
            dpp_id=dpp_id,
            **data.model_dump()
        )
        self.session.add(detail)
        self.session.commit()
        self.session.refresh(detail)
        return detail

    def delete_extra_detail(self, user: User, dpp_id: uuid.UUID, detail_id: uuid.UUID):
        """
        Removes a custom detail.
        """
        # We verify tenant_id directly on the detail now for stricter security
        detail = self.session.exec(
            select(DPPExtraDetail).where(
                DPPExtraDetail.id == detail_id,
                DPPExtraDetail.dpp_id == dpp_id,
                DPPExtraDetail.tenant_id == user._tenant_id
            )
        ).first()

        if detail:
            self.session.delete(detail)
            self.session.commit()
        else:
            raise HTTPException(status_code=404, detail="Detail not found")

    def delete_passport(self, user: User, dpp_id: uuid.UUID):
        """
            Deletes the Digital Product Passport.

            Due to cascade settings in the schema, this will automatically 
            delete associated Events and Extra Details, but the 
            physical 'Product' entity remains intact.
            """
        # Reuse existing getter to ensure tenant isolation check
        dpp = self.get_passport_by_id(user, dpp_id)

        self.session.delete(dpp)
        self.session.commit()
