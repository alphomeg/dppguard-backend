import uuid
from typing import List, Optional
from fastapi import HTTPException, status
from sqlmodel import Session, select
from sqlalchemy.orm import selectinload

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

    def _get_passport_query(self, user: User, dpp_id: uuid.UUID):
        """Helper to ensure tenant isolation via Product join."""
        return (
            select(DigitalProductPassport)
            .join(Product)
            .where(
                DigitalProductPassport.id == dpp_id,
                Product.tenant_id == user._tenant_id
            )
        )

    def get_passport_by_id(self, user: User, dpp_id: uuid.UUID) -> DigitalProductPassport:
        dpp = self.session.exec(self._get_passport_query(user, dpp_id)).first()
        if not dpp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Digital Product Passport not found or access denied."
            )
        return dpp

    def create_passport(self, user: User, data: DPPCreate) -> DigitalProductPassport:
        # 1. Verify Product ownership
        product = self.session.exec(
            select(Product).where(
                Product.id == data.product_id,
                Product.tenant_id == user._tenant_id
            )
        ).first()

        if not product:
            raise HTTPException(status_code=404, detail="Product not found.")

        # 2. Check if Passport already exists (1:1 Restriction)
        # Note: We can check product.passport relationship directly if loaded,
        # but a query is safer to avoid stale object issues.
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
        # In production, use nanoid or shortuuid for cleaner URLs
        public_uid = data.public_uid or str(uuid.uuid4())

        # 4. Create
        dpp = DigitalProductPassport(
            product_id=data.product_id,
            target_url=data.target_url,
            status=data.status,
            public_uid=public_uid
        )

        self.session.add(dpp)
        self.session.commit()
        self.session.refresh(dpp)
        return dpp

    def get_passport_full(self, user: User, dpp_id: uuid.UUID) -> DPPFullDetailsRead:
        """
        Fetches the Passport with Events and Extra Details.
        """
        query = (
            self._get_passport_query(user, dpp_id)
            .options(
                selectinload(DigitalProductPassport.events),
                selectinload(DigitalProductPassport.extra_details)
            )
        )

        dpp = self.session.exec(query).first()
        if not dpp:
            raise HTTPException(status_code=404, detail="Passport not found")

        # Use SQLModel's validate/dump to map to the Read model
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
        Manually adds an audit log entry (e.g. 'Product Shipped', 'Maintenance Performed').
        """
        # Security check
        self.get_passport_by_id(user, dpp_id)

        event = DPPEvent(
            dpp_id=dpp_id,
            actor_id=user.id,  # Record who triggered this
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

        # Optional: Check uniqueness of 'key' within this passport
        # If key exists, update it? Or raise error? Let's allow duplicates or handle upsert manually.
        # Here we just append.

        detail = DPPExtraDetail(dpp_id=dpp_id, **data.model_dump())
        self.session.add(detail)
        self.session.commit()
        self.session.refresh(detail)
        return detail

    def delete_extra_detail(self, user: User, dpp_id: uuid.UUID, detail_id: uuid.UUID):
        """
        Removes a custom detail.
        """
        # Ensure user owns the passport containing the detail
        dpp = self.get_passport_by_id(user, dpp_id)

        detail = self.session.exec(
            select(DPPExtraDetail).where(
                DPPExtraDetail.id == detail_id,
                DPPExtraDetail.dpp_id == dpp.id
            )
        ).first()

        if detail:
            self.session.delete(detail)
            self.session.commit()
        else:
            raise HTTPException(status_code=404, detail="Detail not found")
