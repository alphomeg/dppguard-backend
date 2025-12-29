from typing import List, Optional
import uuid
from loguru import logger
from sqlmodel import Session, select, or_, col
from fastapi import HTTPException, status

from app.db.schema import User, Tenant, Certification
from app.models.certification import CertificationCreate, CertificationUpdate, CertificationRead


class CertificationService:
    def __init__(self, session: Session):
        self.session = session

    def _get_tenant_id(self, user: User) -> uuid.UUID:
        tenant_id = getattr(user, "_tenant_id", None)
        if not tenant_id:
            raise HTTPException(
                status_code=403, detail="No active tenant context.")
        return tenant_id

    def list_certifications(self, user: User, query: Optional[str] = None) -> List[CertificationRead]:
        """
        Fetch certifications visible to this tenant (Global + Custom).
        """
        tenant_id = self._get_tenant_id(user)

        # Logic: (System Global) OR (Owned by Tenant)
        statement = select(Certification).where(
            or_(Certification.tenant_id == None,
                Certification.tenant_id == tenant_id)
        )

        if query:
            search_fmt = f"%{query}%"
            statement = statement.where(
                or_(
                    col(Certification.name).ilike(search_fmt),
                    col(Certification.code).ilike(search_fmt),
                    col(Certification.issuer).ilike(search_fmt)
                )
            )

        statement = statement.order_by(Certification.name.asc())
        results = self.session.exec(statement).all()

        return [
            CertificationRead(
                id=c.id,
                name=c.name,
                code=c.code,
                issuer=c.issuer,
                is_system=(c.tenant_id is None)
            )
            for c in results
        ]

    def create_certification(self, user: User, data: CertificationCreate) -> CertificationRead:
        """
        Create a private custom certification.
        """
        tenant_id = self._get_tenant_id(user)

        # Check Code Uniqueness (Global Check)
        existing = self.session.exec(
            select(Certification).where(Certification.code == data.code)
        ).first()

        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Certification code '{data.code}' already exists."
            )

        cert = Certification(
            tenant_id=tenant_id,
            name=data.name,
            code=data.code,
            issuer=data.issuer
        )

        try:
            self.session.add(cert)
            self.session.commit()
            self.session.refresh(cert)

            return CertificationRead(
                id=cert.id,
                name=cert.name,
                code=cert.code,
                issuer=cert.issuer,
                is_system=False
            )
        except Exception as e:
            self.session.rollback()
            logger.error(f"Certification creation failed: {e}")
            raise HTTPException(
                status_code=500, detail="Could not create certification.")

    def update_certification(self, user: User, cert_id: uuid.UUID, data: CertificationUpdate) -> CertificationRead:
        tenant_id = self._get_tenant_id(user)
        cert = self.session.get(Certification, cert_id)

        if not cert:
            raise HTTPException(
                status_code=404, detail="Certification not found.")

        # ACCESS CONTROL
        if cert.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403, detail="You cannot edit System Certifications.")

        if data.name:
            cert.name = data.name
        if data.issuer:
            cert.issuer = data.issuer

        self.session.add(cert)
        self.session.commit()
        self.session.refresh(cert)

        return CertificationRead(
            id=cert.id,
            name=cert.name,
            code=cert.code,
            issuer=cert.issuer,
            is_system=False
        )

    def delete_certification(self, user: User, cert_id: uuid.UUID):
        tenant_id = self._get_tenant_id(user)
        cert = self.session.get(Certification, cert_id)

        if not cert:
            raise HTTPException(
                status_code=404, detail="Certification not found.")

        # ACCESS CONTROL
        if cert.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403, detail="You cannot delete System Certifications.")

        try:
            self.session.delete(cert)
            self.session.commit()
            return {"message": "Certification deleted successfully."}
        except Exception as e:
            self.session.rollback()
            raise HTTPException(
                status_code=400,
                detail="Cannot delete this certification because it is used in records."
            )
