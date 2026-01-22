import uuid
import mimetypes
from datetime import datetime, timezone
from typing import List, Optional
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
    SupplierArtifact, ArtifactType,
    ConnectionStatus, SupplierProfile, TenantConnection,
    CertificateDefinition
)
from app.models.product_contribution import (
    RequestReadList, RequestReadDetail, RequestAction,
    TechnicalDataUpdate, ActivityLogItem, MaterialInput, SubSupplierInput, CertificateInput,
    ProductAssignmentRequest,
    ProductVersionDetailRead, ProductMaterialRead,
    ProductSupplyNodeRead, ProductCertificateRead,
    ProductCollaborationStatusRead
)
from app.core.audit import _perform_audit_log
from app.utils.file_storage import save_upload_file


class ProductContributionService:
    def __init__(self, session: Session):
        self.session = session

    # ==========================================================================
    # HELPERS
    # ==========================================================================

    def _get_supplier_context(self, user: User) -> Tenant:
        """
        Helper: Strictly enforces that the tenant is a SUPPLIER.
        """
        tenant_id = getattr(user, "_tenant_id", None)
        if not tenant_id:
            raise HTTPException(
                status_code=403, detail="No active tenant context.")

        tenant = self.session.get(Tenant, tenant_id)
        if not tenant or tenant.type != TenantType.SUPPLIER:
            raise HTTPException(
                status_code=403,
                detail="Access Forbidden. Only Suppliers can access contribution workflows."
            )
        return tenant

    def _get_brand_context(self, user: User) -> Tenant:
        """
        Helper: Strictly enforces that the tenant is a BRAND.
        """
        tenant_id = getattr(user, "_tenant_id", None)
        if not tenant_id:
            raise HTTPException(
                status_code=403, detail="No active tenant context.")

        tenant = self.session.get(Tenant, tenant_id)
        if not tenant or tenant.type != TenantType.BRAND:
            raise HTTPException(
                status_code=403,
                detail="Access Forbidden. Only Brands can manage assignments."
            )
        return tenant

    def _deep_clone_version(self, source_version: ProductVersion, new_version_sequence: int, new_status: ProductVersionStatus) -> ProductVersion:
        """
        Internal Helper: Creates a deep copy of a ProductVersion.
        Clones: Metadata, Materials, Supply Chain, and Certificate Links.
        Does NOT clone the actual SupplierArtifacts (files), just the references to them.
        """
        # 1. Clone Shell
        new_version = ProductVersion(
            product_id=source_version.product_id,
            supplier_tenant_id=source_version.supplier_tenant_id,
            version_sequence=new_version_sequence,
            version_name=f"{source_version.version_name} (Copy)",
            status=new_status,
            manufacturing_country=source_version.manufacturing_country,
            mass_kg=source_version.mass_kg,
            total_carbon_footprint=source_version.total_carbon_footprint,
            total_energy_mj=source_version.total_energy_mj,
            total_water_usage=source_version.total_water_usage
        )
        self.session.add(new_version)
        self.session.flush()  # Generate ID

        # 2. Clone Materials
        for m in source_version.materials:
            self.session.add(ProductVersionMaterial(
                version_id=new_version.id,
                source_material_definition_id=m.source_material_definition_id,  # Keep lineage
                material_name=m.material_name,
                percentage=m.percentage,
                origin_country=m.origin_country,
                transport_method=m.transport_method,
                batch_number=m.batch_number
            ))

        # 3. Clone Supply Chain
        for s in source_version.supply_chain:
            self.session.add(ProductVersionSupplyNode(
                version_id=new_version.id,
                role=s.role,
                company_name=s.company_name,
                location_country=s.location_country
            ))

        # 4. Clone Certificate Links
        # We create NEW snapshot records pointing to the SAME source artifacts/files
        for c in source_version.certificates:
            self.session.add(ProductVersionCertificate(
                version_id=new_version.id,
                certificate_type_id=c.certificate_type_id,
                source_artifact_id=c.source_artifact_id,  # Link to same vault item
                file_url=c.file_url,                     # Same URL
                file_name=c.file_name,
                file_type=c.file_type,
                snapshot_name=c.snapshot_name,
                snapshot_issuer=c.snapshot_issuer,
                valid_until=c.valid_until,
                reference_number=c.reference_number
            ))

        return new_version

    # ==========================================================================
    # SUPPLIER READ OPERATIONS
    # ==========================================================================

    def list_requests(self, user: User) -> List[RequestReadList]:
        """
        Lists all incoming requests for this supplier.
        """
        supplier = self._get_supplier_context(user)

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
        """
        Full context for the Supplier Contribution Page.
        """
        supplier = self._get_supplier_context(user)

        # 1. Fetch Request
        req = self.session.exec(
            select(ProductContributionRequest)
            .where(ProductContributionRequest.id == request_id)
            .where(ProductContributionRequest.supplier_tenant_id == supplier.id)
            .options(selectinload(ProductContributionRequest.comments))
        ).first()

        if not req:
            raise HTTPException(status_code=404, detail="Request not found.")

        # 2. Fetch Graph (Version + Children)
        version = self.session.exec(
            select(ProductVersion)
            .where(ProductVersion.id == req.current_version_id)
            .options(
                selectinload(ProductVersion.materials),
                selectinload(ProductVersion.supply_chain),
                selectinload(ProductVersion.certificates),
                selectinload(ProductVersion.product).options(
                    selectinload(Product.marketing_media)
                )
            )
        ).first()

        product = version.product
        brand = self.session.get(Tenant, req.brand_tenant_id)

        # 3. Map Activity Log
        history_items = []
        # Initial Event
        history_items.append(ActivityLogItem(
            id=req.id,
            type='status_change',
            title='Request Received',
            date=req.created_at,
            user_name=brand.name
        ))

        # Comments
        for c in req.comments:
            author = self.session.get(User, c.author_user_id)
            name = f"{author.first_name} {author.last_name}" if author else "System"
            history_items.append(ActivityLogItem(
                id=c.id,
                type='comment',
                title='Comment' if not c.is_rejection_reason else 'Changes Requested',
                date=c.created_at,
                user_name=name,
                note=c.body
            ))

        history_items.sort(key=lambda x: x.date, reverse=True)

        # 4. Map Technical Data (Draft State)
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
                    transport_method=m.transport_method
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
                    id=str(c.id),  # Return ID of the link, not the artifact
                    certificate_type_id=c.certificate_type_id,
                    name=c.snapshot_name,
                    expiry_date=c.valid_until,
                    file_url=c.file_url
                ) for c in version.certificates
            ]
        )

        # 5. Map Product Images (Marketing)
        images = [m.file_url for m in product.marketing_media if not m.is_deleted]

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

    # ==========================================================================
    # SUPPLIER WRITE OPERATIONS
    # ==========================================================================

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
        supplier = self._get_supplier_context(user)

        req = self.session.get(ProductContributionRequest, request_id)
        if not req or req.supplier_tenant_id != supplier.id:
            raise HTTPException(status_code=404, detail="Request not found.")

        version = self.session.get(ProductVersion, req.current_version_id)

        # Workflow State Machine
        if data.action == "accept":
            if req.status != RequestStatus.SENT:
                raise HTTPException(
                    status_code=400, detail="Can only accept 'Sent' requests.")

            req.status = RequestStatus.IN_PROGRESS
            # Ensure version is editable
            version.status = ProductVersionStatus.DRAFT

        elif data.action == "decline":
            req.status = RequestStatus.DECLINED
            version.status = ProductVersionStatus.REJECTED

        elif data.action == "submit":
            if req.status not in [RequestStatus.IN_PROGRESS, RequestStatus.CHANGES_REQUESTED]:
                raise HTTPException(
                    status_code=400, detail="Request must be In Progress to submit.")

            # LOCK DATA
            req.status = RequestStatus.SUBMITTED
            version.status = ProductVersionStatus.SUBMITTED

        else:
            raise HTTPException(status_code=400, detail="Invalid action.")

        # Add Note
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
            _perform_audit_log,
            tenant_id=supplier.id,
            user_id=user.id,
            entity_type="ProductContributionRequest",
            entity_id=req.id,
            action=AuditAction.UPDATE,
            changes={"status": req.status, "action": data.action}
        )

        return {"message": f"Request {data.action}ed successfully."}

    def save_draft_data(
        self,
        user: User,
        request_id: uuid.UUID,
        data: TechnicalDataUpdate,
        files: List[UploadFile],
        background_tasks: BackgroundTasks
    ):
        """
        Saves the form data. 
        Handles scalar updates, list replacement (BOM/Supply Chain), and File Uploads.
        """
        supplier = self._get_supplier_context(user)

        req = self.session.get(ProductContributionRequest, request_id)
        if not req or req.supplier_tenant_id != supplier.id:
            raise HTTPException(status_code=404, detail="Request not found.")

        # Integrity Check: Is it editable?
        if req.status not in [RequestStatus.IN_PROGRESS, RequestStatus.CHANGES_REQUESTED, RequestStatus.ACCEPTED]:
            raise HTTPException(
                status_code=400, detail="Cannot edit data in current status.")

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

        # 2. Update Materials (Full Replace Strategy)
        for m in list(version.materials):
            self.session.delete(m)
        version.materials = []  # Clear logic list

        for m_in in data.materials:
            self.session.add(ProductVersionMaterial(
                version_id=version.id,
                material_name=m_in.name,
                percentage=m_in.percentage,
                origin_country=m_in.origin_country,
                transport_method=m_in.transport_method
            ))

        # 3. Update Supply Chain (Full Replace Strategy)
        for s in list(version.supply_chain):
            self.session.delete(s)
        version.supply_chain = []

        for s_in in data.sub_suppliers:
            self.session.add(ProductVersionSupplyNode(
                version_id=version.id,
                role=s_in.role,
                company_name=s_in.name,
                location_country=s_in.country
            ))

        # 4. Handle Certificates
        # Map uploaded files by their internal ID from the frontend (temp_file_id)
        file_map = {f.filename: f for f in files}

        # Clear existing certificate links
        # (We recreate them to ensure the list matches the frontend state exactly)
        for old_cert in list(version.certificates):
            self.session.delete(old_cert)
        version.certificates = []

        for cert_input in data.certificates:
            final_file_url = cert_input.file_url
            artifact_id = None
            detected_content_type = "application/octet-stream"

            # CASE A: NEW FILE UPLOAD
            if cert_input.temp_file_id and cert_input.temp_file_id in file_map:
                uploaded_file = file_map[cert_input.temp_file_id]

                # Detect MIME
                if uploaded_file.content_type:
                    detected_content_type = uploaded_file.content_type
                else:
                    mime, _ = mimetypes.guess_type(uploaded_file.filename)
                    if mime:
                        detected_content_type = mime

                # Save to S3/Local
                saved_url = save_upload_file(uploaded_file)

                # Register in Supplier's Vault (SupplierArtifact)
                artifact = SupplierArtifact(
                    tenant_id=supplier.id,
                    file_name=uploaded_file.filename,
                    display_name=cert_input.name,
                    file_url=saved_url,
                    file_type=ArtifactType.CERTIFICATE
                )
                self.session.add(artifact)
                self.session.flush()  # Get ID

                final_file_url = saved_url
                artifact_id = artifact.id

            # CASE B: EXISTING FILE (NO NEW UPLOAD)
            elif final_file_url:
                # We assume the user didn't change the file, just maybe the metadata.
                # If the Frontend sent us the 'id' (ProductVersionCertificate ID),
                # we could ideally look up the old record to find the 'source_artifact_id'.
                # For simplicity in 'Full Replace', we might lose the artifact link if not careful.
                # *Improvement*: You can query the deleted objects to recover the artifact_id if needed.

                # Guess Type for Snapshot
                mime, _ = mimetypes.guess_type(final_file_url)
                if mime:
                    detected_content_type = mime

            # Create Link (Snapshot)
            if final_file_url:
                new_link = ProductVersionCertificate(
                    version_id=version.id,
                    certificate_type_id=cert_input.certificate_type_id,
                    # Might be None if existing and we didn't recover it, but URL is safe
                    source_artifact_id=artifact_id,
                    snapshot_name=cert_input.name,
                    snapshot_issuer="Unknown",  # Could be added to form input later
                    valid_until=cert_input.expiry_date,
                    file_url=final_file_url,
                    file_name=cert_input.name,
                    file_type=detected_content_type
                )
                self.session.add(new_link)

        self.session.add(version)
        self.session.commit()

        return {"message": "Draft saved successfully."}

    def add_comment(self, user: User, request_id: uuid.UUID, body: str):
        """
        Add a comment to the chat thread.
        """
        # Allow both Brand and Supplier? The logic usually depends on who 'user' is.
        # This generic method checks if the user belongs to either side.
        tenant_id = getattr(user, "_tenant_id", None)
        req = self.session.get(ProductContributionRequest, request_id)

        if not req:
            raise HTTPException(status_code=404, detail="Request not found.")

        if req.brand_tenant_id != tenant_id and req.supplier_tenant_id != tenant_id:
            raise HTTPException(
                status_code=403, detail="Access denied to this request.")

        comment = CollaborationComment(
            request_id=req.id,
            author_user_id=user.id,
            body=body
        )
        self.session.add(comment)
        self.session.commit()
        return {"message": "Comment added."}

    # ==========================================================================
    # BRAND OPERATIONS (ASSIGNMENT & REVIEW)
    # ==========================================================================

    def assign_product(
        self,
        user: User,
        product_id: uuid.UUID,
        data: ProductAssignmentRequest,
        background_tasks: BackgroundTasks
    ):
        """
        Assigns a Product to a Supplier.
        Handles: First assignment, Re-assignment, and New Version creation.
        """
        brand = self._get_brand_context(user)

        # 1. Fetch Product
        product = self.session.get(Product, product_id)
        if not product or product.tenant_id != brand.id:
            raise HTTPException(status_code=404, detail="Product not found.")

        # 2. Verify Connection via Profile
        profile = self.session.get(SupplierProfile, data.supplier_profile_id)
        if not profile or profile.tenant_id != brand.id:
            raise HTTPException(
                status_code=404, detail="Supplier profile not found.")

        connection = profile.connection
        if not connection or connection.status != ConnectionStatus.ACTIVE or not connection.supplier_tenant_id:
            raise HTTPException(
                status_code=400, detail="Supplier connection is not active or fully onboarded.")

        real_supplier_id = connection.supplier_tenant_id

        # 3. Determine Version Strategy
        existing_versions = self.session.exec(
            select(ProductVersion)
            .where(ProductVersion.product_id == product.id)
            .order_by(ProductVersion.version_sequence.desc())
        ).all()

        target_version = None

        if not existing_versions:
            # SCENARIO A: First Assignment (Create v1)
            v_name = product.pending_version_name or "Initial Version"
            target_version = ProductVersion(
                product_id=product.id,
                supplier_tenant_id=real_supplier_id,
                version_sequence=1,
                version_name=v_name,
                status=ProductVersionStatus.DRAFT
            )
            self.session.add(target_version)
            self.session.flush()

            # Clear pending name from shell
            product.pending_version_name = None
            self.session.add(product)

        else:
            latest = existing_versions[0]

            if latest.status in [ProductVersionStatus.APPROVED, ProductVersionStatus.SUBMITTED]:
                # SCENARIO B: Locked -> Clone new Draft (v2, v3...)
                # DEEP CLONE so supplier doesn't start from scratch
                target_version = self._deep_clone_version(
                    source_version=latest,
                    new_version_sequence=latest.version_sequence + 1,
                    new_status=ProductVersionStatus.DRAFT
                )
                # Assign to potentially new supplier
                target_version.supplier_tenant_id = real_supplier_id
                self.session.add(target_version)
                self.session.flush()

            else:
                # SCENARIO C: Existing Draft -> Reuse
                # If re-assigning to a different supplier, update ownership
                if latest.supplier_tenant_id != real_supplier_id:
                    latest.supplier_tenant_id = real_supplier_id
                    self.session.add(latest)

                target_version = latest

        # 4. Check for Duplicate Active Requests
        active_statuses = [
            RequestStatus.SENT, RequestStatus.ACCEPTED,
            RequestStatus.IN_PROGRESS, RequestStatus.CHANGES_REQUESTED,
            RequestStatus.SUBMITTED
        ]

        existing_req = self.session.exec(
            select(ProductContributionRequest)
            .where(ProductContributionRequest.current_version_id == target_version.id)
            .where(ProductContributionRequest.status.in_(active_statuses))
        ).first()

        if existing_req:
            raise HTTPException(
                status_code=400,
                detail=f"An active request ({existing_req.status}) already exists for this version."
            )

        # 5. Create Request
        request = ProductContributionRequest(
            connection_id=connection.id,
            brand_tenant_id=brand.id,
            supplier_tenant_id=real_supplier_id,
            initial_version_id=target_version.id,
            current_version_id=target_version.id,
            due_date=data.due_date,
            request_note=data.request_note,
            status=RequestStatus.SENT
        )
        self.session.add(request)

        # Add Note as Comment
        if data.request_note:
            self.session.add(CollaborationComment(
                request_id=request.id,
                author_user_id=user.id,
                body=data.request_note
            ))

        self.session.commit()
        self.session.refresh(request)

        # Audit
        background_tasks.add_task(
            _perform_audit_log,
            tenant_id=brand.id,
            user_id=user.id,
            entity_type="ProductContributionRequest",
            entity_id=request.id,
            action=AuditAction.CREATE,
            changes={
                "product_id": str(product.id),
                "supplier_profile_id": str(profile.id),
                "version_sequence": target_version.version_sequence
            }
        )

        return {"message": "Assignment sent successfully", "request_id": request.id}

    def get_latest_version_detail(self, user: User, product_id: uuid.UUID) -> ProductVersionDetailRead:
        """
        Brand View: Fetches the full technical data for the LATEST active version.
        """
        brand = self._get_brand_context(user)

        product = self.session.get(Product, product_id)
        if not product or product.tenant_id != brand.id:
            raise HTTPException(status_code=404, detail="Product not found.")

        # Eager Load
        statement = (
            select(ProductVersion)
            .where(ProductVersion.product_id == product_id)
            .order_by(ProductVersion.version_sequence.desc())
            .options(
                selectinload(ProductVersion.materials),
                selectinload(ProductVersion.supply_chain),
                selectinload(ProductVersion.certificates)
            )
        )
        version = self.session.exec(statement).first()

        if not version:
            raise HTTPException(
                status_code=404, detail="No technical versions found.")

        return ProductVersionDetailRead(
            id=version.id,
            version_sequence=version.version_sequence,
            version_name=version.version_name,
            status=version.status,
            created_at=version.created_at,
            updated_at=version.updated_at,
            manufacturing_country=version.manufacturing_country,
            mass_kg=version.mass_kg,
            total_carbon_footprint=version.total_carbon_footprint,
            total_energy_mj=version.total_energy_mj,
            total_water_usage=version.total_water_usage,

            materials=[ProductMaterialRead(
                id=m.id,
                material_name=m.material_name,
                percentage=m.percentage,
                origin_country=m.origin_country,
                transport_method=m.transport_method
            ) for m in version.materials],

            supply_chain=[ProductSupplyNodeRead(
                id=s.id,
                role=s.role,
                company_name=s.company_name,
                location_country=s.location_country
            ) for s in version.supply_chain],

            certificates=[ProductCertificateRead(
                id=c.id,
                certificate_type_id=c.certificate_type_id,
                snapshot_name=c.snapshot_name,
                snapshot_issuer=c.snapshot_issuer,
                valid_until=c.valid_until,
                file_url=c.file_url,
                file_type=c.file_type
            ) for c in version.certificates]
        )

    def get_collaboration_status(self, user: User, product_id: uuid.UUID) -> ProductCollaborationStatusRead:
        """
        Returns the current workflow status of the product.
        """
        brand = self._get_brand_context(user)

        product = self.session.get(Product, product_id)
        if not product or product.tenant_id != brand.id:
            raise HTTPException(status_code=404, detail="Product not found.")

        version = self.session.exec(
            select(ProductVersion)
            .where(ProductVersion.product_id == product_id)
            .order_by(ProductVersion.version_sequence.desc())
        ).first()

        if not version:
            return ProductCollaborationStatusRead(
                active_request_id=None,
                product_id=product.id,
                latest_version_id=None,
                request_status=None,
                version_status=ProductVersionStatus.DRAFT,
                last_updated_at=product.updated_at
            )

        # Get latest request associated with this version
        request = self.session.exec(
            select(ProductContributionRequest)
            .where(ProductContributionRequest.current_version_id == version.id)
            .where(ProductContributionRequest.brand_tenant_id == brand.id)
            .order_by(ProductContributionRequest.created_at.desc())
        ).first()

        supplier_name = None
        supplier_country = None
        supplier_profile_id = None

        if request:
            # Resolve Supplier Info
            supplier = self.session.get(Tenant, request.supplier_tenant_id)
            if supplier:
                supplier_name = supplier.name
                supplier_country = supplier.location_country

            # Resolve Connection Profile Info
            connection = self.session.get(
                TenantConnection, request.connection_id)
            if connection:
                supplier_profile_id = connection.supplier_profile_id

        return ProductCollaborationStatusRead(
            active_request_id=request.id if request else None,
            product_id=product.id,
            latest_version_id=version.id,
            request_status=request.status if request else None,
            version_status=version.status,
            assigned_supplier_name=supplier_name,
            assigned_supplier_profile_id=supplier_profile_id,
            supplier_country=supplier_country,
            due_date=request.due_date if request else None,
            last_updated_at=request.updated_at if request else version.updated_at
        )

    def cancel_request(self, user: User, product_id: uuid.UUID, request_id: uuid.UUID, reason: str):
        brand = self._get_brand_context(user)

        request = self.session.get(ProductContributionRequest, request_id)
        if not request or request.brand_tenant_id != brand.id:
            raise HTTPException(status_code=404, detail="Request not found.")

        if request.status in [RequestStatus.COMPLETED, RequestStatus.SUBMITTED, RequestStatus.CANCELLED]:
            raise HTTPException(
                status_code=400, detail="Cannot cancel request in current status.")

        request.status = RequestStatus.CANCELLED

        self.session.add(CollaborationComment(
            request_id=request.id,
            author_user_id=user.id,
            body=f"Request Cancelled: {reason}",
            is_rejection_reason=True
        ))

        self.session.add(request)
        self.session.commit()
        return {"message": "Request cancelled"}

    def review_submission(self, user: User, product_id: uuid.UUID, request_id: uuid.UUID, action: str, comment_text: Optional[str] = None):
        """
        Brand Action: Approve or Request Changes.
        """
        brand = self._get_brand_context(user)

        request = self.session.get(ProductContributionRequest, request_id)
        if not request or request.brand_tenant_id != brand.id:
            raise HTTPException(status_code=404, detail="Request not found.")

        version = self.session.get(ProductVersion, request.current_version_id)

        if comment_text:
            self.session.add(CollaborationComment(
                request_id=request.id,
                author_user_id=user.id,
                body=comment_text,
                is_rejection_reason=(action == 'request_changes')
            ))

        if action == 'approve':
            request.status = RequestStatus.COMPLETED
            version.status = ProductVersionStatus.APPROVED

        elif action == 'request_changes':
            request.status = RequestStatus.CHANGES_REQUESTED
            # Unlock version for Supplier
            version.status = ProductVersionStatus.DRAFT

        else:
            raise HTTPException(status_code=400, detail="Invalid action.")

        self.session.add(request)
        self.session.add(version)
        self.session.commit()

        return {"message": f"Submission {action}d successfully."}
