import uuid
import mimetypes
from typing import List
from loguru import logger
from sqlmodel import Session, select
from fastapi import HTTPException, BackgroundTasks, UploadFile
from sqlalchemy.orm import selectinload


from app.db.schema import (
    User, Tenant, TenantType,
    ProductContributionRequest,
    ProductVersion, ProductVersionStatus,
    CollaborationComment, AuditAction, RequestStatus, Product,
    ProductVersionMaterial, ProductVersionSupplyNode, ProductVersionCertificate,
    SupplierArtifact, ArtifactType
)
from app.models.product_contribution import (
    RequestReadList, RequestReadDetail, RequestAction,
    TechnicalDataUpdate, ActivityLogItem, MaterialInput, SubSupplierInput, CertificateInput
)
from app.core.audit import _perform_audit_log
from app.utils.file_storage import save_upload_file


class ProductContributionService:
    def __init__(self, session: Session):
        self.session = session

    def _get_supplier_tenant(self, user: User) -> Tenant:
        """Enforce Supplier Access Only."""
        tenant_id = getattr(user, "_tenant_id", None)
        tenant = self.session.get(Tenant, tenant_id)
        if not tenant or tenant.type != TenantType.SUPPLIER:
            raise HTTPException(
                403, "Only Suppliers can access contribution workflows.")
        return tenant

    # ==========================
    # DASHBOARD & READ
    # ==========================

    def list_requests(self, user: User) -> List[RequestReadList]:
        """Lists all incoming requests for this supplier."""
        supplier = self._get_supplier_tenant(user)

        # Join with Product/Version for display info
        statement = (
            select(ProductContributionRequest, Product, ProductVersion)
            .join(ProductVersion, ProductContributionRequest.current_version_id == ProductVersion.id)
            .join(Product, ProductVersion.product_id == Product.id)
            .where(ProductContributionRequest.supplier_tenant_id == supplier.id)
            .order_by(ProductContributionRequest.updated_at.desc())
        )

        results = self.session.exec(statement).all()

        output = []
        for req, prod, ver in results:
            # Fetch Brand Name (Requester)
            brand = self.session.get(Tenant, req.brand_tenant_id)

            output.append(RequestReadList(
                id=req.id,
                brand_name=brand.name if brand else "Unknown Brand",
                product_name=prod.name,
                product_image_url=prod.main_image_url,
                sku=prod.sku,
                version_name=ver.version_name,
                due_date=req.due_date,
                status=req.status,
                updated_at=req.updated_at
            ))
        return output

    def get_request_detail(self, user: User, request_id: uuid.UUID) -> RequestReadDetail:
        supplier = self._get_supplier_tenant(user)

        # 1. Fetch Request
        req = self.session.exec(
            select(ProductContributionRequest)
            .where(ProductContributionRequest.id == request_id)
            .where(ProductContributionRequest.supplier_tenant_id == supplier.id)
            .options(selectinload(ProductContributionRequest.comments))
        ).first()

        if not req:
            raise HTTPException(404, "Request not found.")

        # 2. Fetch Graph
        version = self.session.exec(
            select(ProductVersion)
            .where(ProductVersion.id == req.current_version_id)
            .options(
                selectinload(ProductVersion.materials),
                selectinload(ProductVersion.supply_chain),
                selectinload(ProductVersion.certificates),
                selectinload(ProductVersion.product).options(
                    selectinload(Product.marketing_media))
            )
        ).first()

        product = version.product
        brand = self.session.get(Tenant, req.brand_tenant_id)

        # 3. Map Activity Log (History)
        history_items = []
        # Add creation event
        history_items.append(ActivityLogItem(
            id=req.id,  # pseudo id
            type='status_change',
            title='Request Received',
            date=req.created_at,
            user_name=brand.name
        ))

        # Add comments
        for c in req.comments:
            author = self.session.get(User, c.author_user_id)
            name = f"{author.first_name} {author.last_name}" if author else "Unknown"
            history_items.append(ActivityLogItem(
                id=c.id,
                type='comment',
                title='Comment Added',
                date=c.created_at,
                user_name=name,
                note=c.body
            ))

        # Sort history
        history_items.sort(key=lambda x: x.date, reverse=True)

        # 4. Map Technical Data
        draft_data = TechnicalDataUpdate(
            manufacturing_country=version.manufacturing_country,
            total_carbon_footprint=version.total_carbon_footprint,
            total_energy_mj=version.total_energy_mj,
            total_water_usage=version.total_water_usage,

            materials=[
                MaterialInput(
                    name=m.material_name,
                    percentage=m.percentage,
                    origin_country=m.origin_country,
                    # transport_method=m.transport_method # Add to schema if missing
                ) for m in version.materials
            ],

            sub_suppliers=[
                SubSupplierInput(
                    role=s.role,
                    name=s.company_name,
                    country=s.location_country
                ) for s in version.supply_chain
            ],

            certificates=[
                CertificateInput(
                    # Return the Certificate ID (ProductVersionCertificate ID)
                    id=str(c.id),

                    # FIX: Populate the missing field
                    certificate_type_id=c.certificate_type_id,

                    name=c.snapshot_name,
                    expiry_date=c.valid_until,
                    file_url=c.file_url
                ) for c in version.certificates
            ]
        )

        # 5. Map Images
        images = [
            m.file_url for m in product.marketing_media if not m.is_deleted] if product.marketing_media else []

        return RequestReadDetail(
            id=req.id,
            brand_name=brand.name,
            status=req.status,
            due_date=req.due_date,
            request_note=req.request_note,
            updated_at=req.updated_at,
            product_name=product.name,
            sku=product.sku,
            product_description=product.description,
            product_images=images,
            version_name=version.version_name,
            current_draft=draft_data,
            history=history_items
        )

    # ==========================
    # WORKFLOW ACTIONS
    # ==========================

    def handle_workflow_action(
        self,
        user: User,
        request_id: uuid.UUID,
        data: RequestAction,
        background_tasks: BackgroundTasks
    ):
        """
        Accept, Decline, or Submit the request.
        """
        supplier = self._get_supplier_tenant(user)
        req = self.session.get(ProductContributionRequest, request_id)

        if not req or req.supplier_tenant_id != supplier.id:
            raise HTTPException(404, "Request not found.")

        version = self.session.get(ProductVersion, req.current_version_id)

        if data.action == "accept":
            if req.status != RequestStatus.SENT:
                raise HTTPException(400, "Can only accept 'Sent' requests.")
            req.status = RequestStatus.IN_PROGRESS
            # Automatically start the draft on the version
            version.status = ProductVersionStatus.DRAFT

        elif data.action == "decline":
            req.status = RequestStatus.DECLINED
            version.status = ProductVersionStatus.REJECTED  # Or specialized status

        elif data.action == "submit":
            if req.status not in [RequestStatus.IN_PROGRESS, RequestStatus.CHANGES_REQUESTED]:
                raise HTTPException(
                    400, "Request must be in progress to submit.")

            # LOCK THE VERSION
            req.status = RequestStatus.SUBMITTED
            version.status = ProductVersionStatus.SUBMITTED

        else:
            raise HTTPException(400, "Invalid action.")

        # Add Note if provided
        if data.note:
            self.session.add(CollaborationComment(
                request_id=req.id,
                author_user_id=user.id,
                body=data.note
            ))

        self.session.add(req)
        self.session.add(version)
        self.session.commit()

        # Audit
        background_tasks.add_task(
            _perform_audit_log, tenant_id=supplier.id, user_id=user.id,
            entity_type="ProductContributionRequest", entity_id=req.id,
            action=AuditAction.UPDATE, changes={
                "status": req.status, "action": data.action}
        )

        return {"message": f"Request {data.action}ed successfully."}

    # ==========================
    # DATA ENTRY (FILLING THE FORM)
    # ==========================

    def save_draft_data(
        self,
        user: User,
        request_id: uuid.UUID,
        data: TechnicalDataUpdate,
        files: List[UploadFile],
        background_tasks: BackgroundTasks
    ):
        supplier = self._get_supplier_tenant(user)
        req = self.session.get(ProductContributionRequest, request_id)

        if not req or req.supplier_tenant_id != supplier.id:
            raise HTTPException(404, "Request not found.")

        version = self.session.get(ProductVersion, req.current_version_id)

        # 1. Update Scalars
        if data.manufacturing_country is not None:
            version.manufacturing_country = data.manufacturing_country
        if data.total_carbon_footprint is not None:
            version.total_carbon_footprint = data.total_carbon_footprint
        if data.total_energy_mj is not None:
            version.total_energy_mj = data.total_energy_mj
        if data.total_water_usage is not None:
            version.total_water_usage = data.total_water_usage

        # 2. Update Materials (Full Replace)
        # FIX: Iterate over a copy, delete, then CLEAR the list on the parent
        for m in list(version.materials):
            self.session.delete(m)

        version.materials = []  # <--- Critical Line

        for m_in in data.materials:
            self.session.add(ProductVersionMaterial(
                version_id=version.id,
                material_name=m_in.name,
                percentage=m_in.percentage,
                origin_country=m_in.origin_country,
                # transport=m_in.transport_method
            ))

        # 3. Update Supply Chain (Full Replace)
        for s in list(version.supply_chain):
            self.session.delete(s)
        version.supply_chain = []  # <--- Critical Line

        for s_in in data.sub_suppliers:
            self.session.add(ProductVersionSupplyNode(
                version_id=version.id,
                role=s_in.role,
                company_name=s_in.name,
                location_country=s_in.country
            ))

        # 4. Handle Certificates
        # Map temp_ids to files
        file_map = {f.filename: f for f in files}

        # Clear existing links
        for old_cert in list(version.certificates):
            self.session.delete(old_cert)

        version.certificates = []

        for cert_input in data.certificates:
            final_file_url = cert_input.file_url
            artifact_id = None

            # Default to generic, will be overwritten
            detected_content_type = "application/octet-stream"

            # A. HANDLE NEW FILE UPLOAD
            if cert_input.temp_file_id and cert_input.temp_file_id in file_map:
                uploaded_file = file_map[cert_input.temp_file_id]

                # 1. Detect Mime Type
                # Primary: What the browser said
                if uploaded_file.content_type and uploaded_file.content_type != "application/octet-stream":
                    detected_content_type = uploaded_file.content_type
                else:
                    # Fallback: Guess from extension
                    mime, _ = mimetypes.guess_type(uploaded_file.filename)
                    if mime:
                        detected_content_type = mime

                # 2. Save File
                saved_url = save_upload_file(uploaded_file)

                # 3. Create Artifact
                artifact = SupplierArtifact(
                    tenant_id=supplier.id,
                    file_name=uploaded_file.filename,
                    display_name=cert_input.name,
                    file_url=saved_url,
                    file_type=ArtifactType.CERTIFICATE
                )
                self.session.add(artifact)
                self.session.flush()

                final_file_url = saved_url
                artifact_id = artifact.id

            # B. HANDLE EXISTING FILE (NO NEW UPLOAD)
            elif final_file_url:
                # Try to preserve existing type or guess from URL extension
                # (If we had the original ProductVersionCertificate object here we could copy it,
                # but for simplicity in this Draft-Replace logic, guessing is safe)
                mime, _ = mimetypes.guess_type(final_file_url)
                if mime:
                    detected_content_type = mime
                elif final_file_url.endswith(".pdf"):
                    detected_content_type = "application/pdf"
                elif final_file_url.endswith((".jpg", ".jpeg")):
                    detected_content_type = "image/jpeg"
                elif final_file_url.endswith(".png"):
                    detected_content_type = "image/png"

            # C. CREATE LINK
            if final_file_url:
                new_link = ProductVersionCertificate(
                    version_id=version.id,
                    certificate_type_id=cert_input.certificate_type_id,
                    source_artifact_id=artifact_id,
                    snapshot_name=cert_input.name,
                    snapshot_issuer="Unknown",
                    valid_until=cert_input.expiry_date,
                    file_url=final_file_url,
                    file_name=cert_input.name,

                    # FIX IS HERE: Use the dynamic variable, do not hardcode
                    file_type=detected_content_type
                )
                self.session.add(new_link)

        self.session.add(version)
        self.session.commit()

        return {"message": "Draft saved with files."}

    def add_comment(self, user: User, request_id: uuid.UUID, body: str):
        """Simple chat function."""
        supplier = self._get_supplier_tenant(user)
        req = self.session.get(ProductContributionRequest, request_id)
        if not req or req.supplier_tenant_id != supplier.id:
            raise HTTPException(404, "Request not found.")

        comment = CollaborationComment(
            request_id=req.id,
            author_user_id=user.id,
            body=body
        )
        self.session.add(comment)
        self.session.commit()
        return {"message": "Comment added."}
