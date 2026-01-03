from uuid import UUID
from sqlmodel import Session, select
from fastapi import HTTPException

from app.db.schema import (
    User, DataContributionRequest, ProductVersion,
    VersionMaterial, VersionSupplier, VersionCertification,
    RequestStatus, VersionStatus, CollaborationComment, SupplierProfile,
    Product, Material
)
from app.models.product_version import VersionDataUpdate
from app.models.data_contribution_request import AssignmentCreate, ReviewPayload


class CollaborationService:
    def __init__(self, session: Session):
        self.session = session

    def assign_supplier(self, user: User, product_id: UUID, data: AssignmentCreate):
        """Creates the initial request."""
        tenant_id = getattr(user, "_tenant_id")

        # 1. Get Latest Version (Must be Draft)
        version = self.session.exec(
            select(ProductVersion)
            .where(ProductVersion.product_id == product_id)
            .order_by(ProductVersion.version_number.desc())
        ).first()

        if not version or version.status != VersionStatus.WORKING_DRAFT:
            raise HTTPException(
                400, "Can only assign suppliers to a Draft version.")

        # 2. Get Connection from Profile
        profile = self.session.get(SupplierProfile, data.supplier_profile_id)
        if not profile or profile.tenant_id != tenant_id:
            raise HTTPException(404, "Supplier profile not found.")

        conn = profile.connection
        if not conn or not conn.supplier_tenant_id:
            raise HTTPException(
                400, "Supplier must be registered on the platform to receive assignments.")

        # 3. Create Request
        request = DataContributionRequest(
            connection_id=conn.id,
            brand_tenant_id=tenant_id,
            supplier_tenant_id=conn.supplier_tenant_id,
            initial_version_id=version.id,
            current_version_id=version.id,
            status=RequestStatus.SENT
        )
        self.session.add(request)
        self.session.commit()
        return {"request_id": request.id}

    def update_data(self, user: User, request_id: UUID, data: VersionDataUpdate):
        """
        Supplier saves draft work.
        Performs a full replace on child lists (Materials, Suppliers, Certs).
        """
        tenant_id = getattr(user, "_tenant_id")
        req = self.session.get(DataContributionRequest, request_id)

        # 1. Validation
        if not req or req.supplier_tenant_id != tenant_id:
            raise HTTPException(403, "Unauthorized access to this request.")

        if req.status not in [RequestStatus.SENT, RequestStatus.IN_PROGRESS, RequestStatus.CHANGES_REQUESTED]:
            raise HTTPException(
                400, "Request is locked/submitted. Cannot edit.")

        version = self.session.get(ProductVersion, req.current_version_id)

        # 2. Update Scalar Fields
        if data.manufacturing_country:
            version.manufacturing_country = data.manufacturing_country
        if data.total_carbon_footprint_kg is not None:
            version.total_carbon_footprint_kg = data.total_carbon_footprint_kg
        if data.total_water_usage_liters is not None:
            version.total_water_usage_liters = data.total_water_usage_liters
        if data.total_energy_mj is not None:
            version.total_energy_mj = data.total_energy_mj
        if data.recycling_instructions:
            version.recycling_instructions = data.recycling_instructions
        if data.recyclability_class:
            version.recyclability_class = data.recyclability_class

        # 3. Update Materials (Full Replace)
        for old in version.materials:
            self.session.delete(old)

        for m in data.materials:
            self.session.add(VersionMaterial(
                version_id=version.id,
                material_id=m.material_id,
                percentage=m.percentage,
                origin_country=m.origin_country,
                transport_method=m.transport_method,
                material_carbon_footprint_kg=m.material_carbon_footprint_kg
            ))

        # 4. Update Supply Chain Map (Full Replace)
        for old in version.suppliers:
            self.session.delete(old)

        for s in data.suppliers:
            self.session.add(VersionSupplier(
                version_id=version.id,
                supplier_id=s.supplier_id,
                role=s.role
            ))

        # 5. Update Certifications (Full Replace)
        for old in version.certifications:
            self.session.delete(old)

        for c in data.certifications:
            self.session.add(VersionCertification(
                version_id=version.id,
                certification_id=c.certification_id,
                document_url=c.document_url,
                valid_until=c.valid_until
            ))

        # 6. Update Request Status
        if req.status == RequestStatus.SENT:
            req.status = RequestStatus.IN_PROGRESS
            self.session.add(req)

        self.session.add(version)
        self.session.commit()
        return {"message": "Draft saved successfully."}

    def review_request(self, user: User, request_id: UUID, payload: ReviewPayload):
        tenant_id = getattr(user, "_tenant_id")
        req = self.session.get(DataContributionRequest, request_id)

        if not req or req.brand_tenant_id != tenant_id:
            raise HTTPException(403, "Only the Brand can review.")

        if req.status != RequestStatus.SUBMITTED:
            raise HTTPException(400, "Request is not submitted for review.")

        current_version = self.session.get(
            ProductVersion, req.current_version_id)

        if payload.approve:
            req.status = RequestStatus.COMPLETED
            current_version.status = VersionStatus.APPROVED
            self.session.add(req)
            self.session.add(current_version)
        else:
            if not payload.comment:
                raise HTTPException(
                    400, "Comment is required when requesting changes.")

            # 1. Archive old version state
            current_version.status = VersionStatus.REVISION_REQUIRED
            self.session.add(current_version)

            # 2. Clone to next version
            new_version = self._clone_version(current_version)
            self.session.add(new_version)
            self.session.flush()

            # 3. Update Request Pointer
            req.current_version_id = new_version.id
            req.status = RequestStatus.CHANGES_REQUESTED
            self.session.add(req)

            # 4. Add Comment
            comment = CollaborationComment(
                request_id=req.id,
                author_user_id=user.id,
                body=payload.comment,
                is_rejection_reason=True
            )
            self.session.add(comment)

        self.session.commit()
        return {"status": req.status}

    def _clone_version(self, source: ProductVersion) -> ProductVersion:
        # Clone Scalar Fields
        new_version = ProductVersion(
            product_id=source.product_id,
            parent_version_id=source.id,
            version_number=source.version_number + 1,
            status=VersionStatus.WORKING_DRAFT,
            created_by_tenant_id=source.created_by_tenant_id,
            product_name_display=source.product_name_display,
            manufacturing_country=source.manufacturing_country,
            total_carbon_footprint_kg=source.total_carbon_footprint_kg,
            total_water_usage_liters=source.total_water_usage_liters,
            total_energy_mj=source.total_energy_mj,
            recycling_instructions=source.recycling_instructions,
            recyclability_class=source.recyclability_class,
            media_gallery=source.media_gallery
        )
        self.session.add(new_version)
        self.session.flush()

        # Clone Materials
        for mat in source.materials:
            new_mat = VersionMaterial(
                version_id=new_version.id,
                material_id=mat.material_id,
                unlisted_material_name=mat.unlisted_material_name,
                is_confidential=mat.is_confidential,
                percentage=mat.percentage,
                origin_country=mat.origin_country,
                material_carbon_footprint_kg=mat.material_carbon_footprint_kg,
                transport_method=mat.transport_method
            )
            self.session.add(new_mat)

        # Clone Certifications
        for cert in source.certifications:
            new_cert = VersionCertification(
                version_id=new_version.id,
                certification_id=cert.certification_id,
                document_url=cert.document_url,
                valid_until=cert.valid_until
            )
            self.session.add(new_cert)

        return new_version

    def get_request(self, user: User, request_id: UUID):
        """
        Fetch request details with enriched Material names.
        """
        tenant_id = getattr(user, "_tenant_id")

        req = self.session.get(DataContributionRequest, request_id)
        if not req:
            raise HTTPException(status_code=404, detail="Request not found.")

        # Access Control
        if req.supplier_tenant_id != tenant_id and req.brand_tenant_id != tenant_id:
            raise HTTPException(
                status_code=403, detail="You do not have access to this request.")

        # Fetch version and product
        version = self.session.get(ProductVersion, req.current_version_id)
        product = self.session.get(Product, version.product_id)

        # --- NEW LOGIC: ENRICH MATERIALS ---
        # 1. Collect all Material IDs
        material_ids = [
            vm.material_id for vm in version.materials if vm.material_id]

        # 2. Batch fetch from Material Library
        materials_map = {}
        if material_ids:
            mats = self.session.exec(select(Material).where(
                Material.id.in_(material_ids))).all()
            materials_map = {m.id: m for m in mats}

        # 3. Construct custom list with names
        enriched_materials = []
        for vm in version.materials:
            # Find the linked library item
            library_mat = materials_map.get(vm.material_id)

            enriched_materials.append({
                "id": vm.id,
                "material_id": vm.material_id,
                # Add the human-readable fields here:
                "material_name": library_mat.name if library_mat else "Unknown Material",
                "material_code": library_mat.code if library_mat else None,
                "percentage": vm.percentage,
                "origin_country": vm.origin_country,
                "is_confidential": vm.is_confidential
            })
        # -----------------------------------

        return {
            "request": {
                "id": req.id,
                "status": req.status,
                "product_name": version.product_name_display,
                "product_sku": product.sku,
                "brand_id": req.brand_tenant_id,
                "supplier_id": req.supplier_tenant_id
            },
            "version": version,
            "materials": enriched_materials,  # Return the enriched list
            "suppliers": version.suppliers,
            "certifications": version.certifications
        }

    def submit_request(self, user: User, request_id: UUID):
        """
        Supplier locks the data and sends to Brand for review.
        """
        tenant_id = getattr(user, "_tenant_id")
        req = self.session.get(DataContributionRequest, request_id)

        # 1. Validation
        if not req:
            raise HTTPException(status_code=404, detail="Request not found.")

        if req.supplier_tenant_id != tenant_id:
            raise HTTPException(
                status_code=403, detail="Only the assigned supplier can submit this request.")

        if req.status not in [RequestStatus.SENT, RequestStatus.IN_PROGRESS, RequestStatus.CHANGES_REQUESTED]:
            raise HTTPException(
                status_code=400, detail="Request cannot be submitted in its current state.")

        # 2. State Transition
        req.status = RequestStatus.SUBMITTED

        # Lock the version as well
        version = self.session.get(ProductVersion, req.current_version_id)
        version.status = VersionStatus.SUBMITTED

        self.session.add(req)
        self.session.add(version)
        self.session.commit()

        return {"message": "Request submitted successfully for review."}
