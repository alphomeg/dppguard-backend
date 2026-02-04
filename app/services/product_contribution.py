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
    CertificateDefinition, TenantMember, MemberStatus
)
from app.models.product_contribution import (
    RequestReadList, RequestReadDetail, RequestAction,
    TechnicalDataUpdate, ActivityLogItem, MaterialInput, SubSupplierInput, CertificateInput,
    ProductAssignmentRequest,
    ProductVersionDetailRead, ProductMaterialRead,
    ProductSupplyNodeRead, ProductCertificateRead,
    ProductSupplyNodeRead, ProductCertificateRead,
    ProductCollaborationStatusRead,
    VersionComparisonResponse, VersionComparisonSnapshot,
    VersionComparisonMaterial, VersionComparisonSupply,
    VersionComparisonImpact, VersionComparisonCertificate
)
from app.core.audit import _perform_audit_log
from app.utils.file_storage import save_upload_file


def _get_certificate_type_value(cert: ProductVersionCertificate) -> str:
    """
    Helper to safely get certificate_type column value, avoiding relationship conflict.
    Since we renamed the relationship to certificate_definition, certificate_type should
    access the column, but we add a safety check.
    """
    # Try to get from instance dict first (most reliable)
    value = getattr(cert, '__dict__', {}).get('certificate_type')
    if isinstance(value, str):
        return value
    # If not in dict or not a string, try direct access
    value = getattr(cert, 'certificate_type', None)
    if isinstance(value, str):
        return value
    # Fallback: if it's the relationship object, get name from it
    if hasattr(value, 'name'):
        return value.name
    # Last resort: use relationship
    if cert.certificate_definition:
        return cert.certificate_definition.name
    return None


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

    def _deep_clone_version(self, source_version: ProductVersion, new_version_sequence: int, new_status: ProductVersionStatus, new_revision: int = 0, version_name: Optional[str] = None) -> ProductVersion:
        """
        Internal Helper: Creates a deep copy of a ProductVersion.
        Clones: Metadata, Materials, Supply Chain, and Certificate Links.
        Does NOT clone the actual SupplierArtifacts (files), just the references to them.
        """
        # Use provided version_name if given, otherwise use logic based on sequence change
        if version_name:
            final_name = version_name
        else:
            # Logic: If major version change, append Copy. If revision, keep name.
            final_name = source_version.version_name
            if new_version_sequence != source_version.version_sequence:
                final_name = f"{source_version.version_name} (Copy)"

        # 1. Clone Shell
        new_version = ProductVersion(
            product_id=source_version.product_id,
            supplier_tenant_id=source_version.supplier_tenant_id,
            version_sequence=new_version_sequence,
            revision=new_revision,
            version_name=final_name,
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
                lineage_id=m.lineage_id,  # PRESERVE lineage
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
                lineage_id=s.lineage_id,  # PRESERVE lineage
                role=s.role,
                company_name=s.company_name,
                location_country=s.location_country
            ))

        # 4. Clone Certificate Links
        # We create NEW snapshot records pointing to the SAME source artifacts/files
        for c in source_version.certificates:
            self.session.add(ProductVersionCertificate(
                version_id=new_version.id,
                lineage_id=c.lineage_id,  # PRESERVE lineage
                certificate_type_id=c.certificate_type_id,  # PRESERVE certificate_type_id (like source_material_definition_id)
                source_artifact_id=c.source_artifact_id,  # Link to same vault item
                file_url=c.file_url,                     # Same URL
                file_name=c.file_name,
                file_type=c.file_type,
                file_size_bytes=c.file_size_bytes,  # Preserve file size
                snapshot_name=c.snapshot_name,
                snapshot_issuer=c.snapshot_issuer,
                # Preserve certificate type (from library or manually entered)
                certificate_type=_get_certificate_type_value(c),
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
                product_description=prod.description,
                product_image_url=prod.main_image_url,
                sku=prod.sku,
                version_name=ver.version_name,
                due_date=req.due_date,
                request_note=req.request_note,
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

            # Determine appropriate title based on comment content and context
            title = 'Comment'
            if c.is_rejection_reason:
                # Check if it's a cancellation comment
                if c.body.startswith("Request Cancelled:"):
                    title = 'Request Cancelled'
                else:
                    title = 'Changes Requested'
            elif req.status == RequestStatus.DECLINED:
                # Check if this comment is from supplier (decline reason)
                # Query author's active membership to determine their tenant
                if author:
                    author_membership = self.session.exec(
                        select(TenantMember)
                        .where(TenantMember.user_id == author.id)
                        .where(TenantMember.status == MemberStatus.ACTIVE)
                    ).first()
                    if author_membership and author_membership.tenant_id == supplier.id:
                        # This is likely the decline reason from supplier
                        title = 'Request Declined'

            history_items.append(ActivityLogItem(
                id=c.id,
                type='comment',
                title=title,
                date=c.created_at,
                user_name=name,
                note=c.body
            ))

        history_items.sort(key=lambda x: x.date, reverse=True)

        # 4. Map Technical Data (Draft State)
        # SECURITY: Only expose technical data if supplier has accepted the request
        # When status is SENT, supplier should only see product info, not technical details
        if req.status == RequestStatus.SENT:
            # Return empty technical data - supplier hasn't accepted yet
            draft_data = TechnicalDataUpdate(
                manufacturing_country=None,
                total_carbon_footprint=None,
                total_energy_mj=None,
                total_water_usage=None,
                materials=[],
                sub_suppliers=[],
                certificates=[]
            )
        else:
            # Supplier has accepted or request is in progress - show full technical data
            
            # Fetch certificate definitions to potentially fix "Unknown" issuers
            cert_type_ids_for_read = [c.certificate_type_id for c in version.certificates if c.certificate_type_id]
            cert_definitions_for_read = {}
            if cert_type_ids_for_read:
                cert_defs_read = self.session.exec(
                    select(CertificateDefinition)
                    .where(CertificateDefinition.id.in_(cert_type_ids_for_read))
                ).all()
                cert_definitions_for_read = {cd.id: cd.issuer_authority for cd in cert_defs_read if cd.issuer_authority and cd.issuer_authority.strip()}

            draft_data = TechnicalDataUpdate(
                manufacturing_country=version.manufacturing_country,
                total_carbon_footprint=version.total_carbon_footprint,
                total_energy_mj=version.total_energy_mj,
                total_water_usage=version.total_water_usage,

                materials=[
                    MaterialInput(
                        lineage_id=m.lineage_id,
                        source_material_definition_id=m.source_material_definition_id,
                        name=m.material_name,
                        percentage=m.percentage,
                        origin_country=m.origin_country,
                        transport_method=m.transport_method
                    ) for m in version.materials
                ],

                sub_suppliers=[
                    SubSupplierInput(
                        lineage_id=s.lineage_id,
                        role=s.role,
                        name=s.company_name,
                        country=s.location_country
                    ) for s in version.supply_chain
                ],

                certificates=[
                    CertificateInput(
                        # Return ID of the link, not the artifact
                        id=str(c.id),
                        lineage_id=c.lineage_id,
                        certificate_type_id=c.certificate_type_id,
                        source_artifact_id=c.source_artifact_id,
                        name=c.snapshot_name,
                        # If issuer is "Unknown" or missing, try to re-fetch from certificate definition
                        issuer=cert_definitions_for_read.get(c.certificate_type_id) if (c.snapshot_issuer == "Unknown" or not c.snapshot_issuer) and c.certificate_type_id and c.certificate_type_id in cert_definitions_for_read else c.snapshot_issuer,
                        # Return certificate name (from library or manually entered)
                        certificate_type=_get_certificate_type_value(c),
                        expiry_date=c.valid_until,
                        file_url=c.file_url,
                        file_name=c.file_name,  # Include filename so frontend can preserve it on updates
                        file_size_bytes=c.file_size_bytes  # Include file size
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
            request_note=req.request_note,  # Brand's initial instruction/comment
            created_at=req.created_at,
            updated_at=req.updated_at,
            product_name=product.name,
            sku=product.sku,
            # Product description for supplier to review
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

            # Ensure version is in acceptable state for acceptance
            # Version should be DRAFT (new assignment) or REJECTED (if previously rejected)
            if version.status not in [ProductVersionStatus.DRAFT, ProductVersionStatus.REJECTED]:
                raise HTTPException(
                    status_code=409,  # Conflict
                    detail=f"Cannot accept request: Version status is {version.status.value}. Expected DRAFT or REJECTED."
                )

            req.status = RequestStatus.IN_PROGRESS
            # Ensure version is editable
            version.status = ProductVersionStatus.DRAFT

        elif data.action == "decline":
            # Suppliers can only decline before submitting (SENT, IN_PROGRESS, or CHANGES_REQUESTED)
            # Once submitted, they must wait for brand review
            if req.status in [RequestStatus.SUBMITTED, RequestStatus.COMPLETED, RequestStatus.DECLINED, RequestStatus.CANCELLED]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot decline request. Current status is '{req.status.value}'. "
                    f"Suppliers can only decline requests that are not yet submitted or completed."
                )

            req.status = RequestStatus.DECLINED
            version.status = ProductVersionStatus.REJECTED

        elif data.action == "submit":
            if req.status not in [RequestStatus.IN_PROGRESS, RequestStatus.CHANGES_REQUESTED]:
                raise HTTPException(
                    status_code=400, detail="Request must be In Progress to submit.")

            # CRITICAL: Ensure version is actually editable before locking it
            if version.status != ProductVersionStatus.DRAFT:
                raise HTTPException(
                    status_code=409,  # Conflict
                    detail=f"Cannot submit: Version is already {version.status.value}. Only DRAFT versions can be submitted."
                )

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
        # NOTE: RequestStatus.ACCEPTED doesn't exist - "accept" action sets status to IN_PROGRESS
        if req.status not in [RequestStatus.IN_PROGRESS, RequestStatus.CHANGES_REQUESTED]:
            raise HTTPException(
                status_code=400, detail="Cannot edit data in current status.")

        version = self.session.get(ProductVersion, req.current_version_id)

        # 2. NEW: Data Integrity Guard (Defense in Depth)
        # CRITICAL: Explicitly block editing when version is SUBMITTED or APPROVED
        # Even if the request says 'In Progress', if the version is locked, we MUST NOT write.
        if version.status in [ProductVersionStatus.SUBMITTED, ProductVersionStatus.APPROVED]:
            raise HTTPException(
                status_code=409,  # Conflict
                detail=f"Cannot edit data: The technical version is locked ({version.status.value}). Supplier cannot modify submitted or approved versions."
            )

        # Additional check: Only DRAFT versions can be edited
        if version.status != ProductVersionStatus.DRAFT:
            raise HTTPException(
                status_code=409,  # Conflict
                detail=f"Cannot edit data: Version must be in DRAFT status to allow edits. Current status: {version.status.value}."
            )

        # 1. Update Scalars
        if data.manufacturing_country is not None:
            version.manufacturing_country = data.manufacturing_country
        if data.total_carbon_footprint is not None:
            version.total_carbon_footprint = data.total_carbon_footprint
        if data.total_energy_mj is not None:
            version.total_energy_mj = data.total_energy_mj
        if data.total_water_usage is not None:
            version.total_water_usage = data.total_water_usage

        # 2. Update Materials (Full Replace Strategy with Lineage Tracking)
        # Build map of existing lineage IDs for validation and preserve source_material_definition_id
        existing_material_lineages = {m.lineage_id for m in version.materials}
        existing_material_definitions = {
            m.lineage_id: m.source_material_definition_id for m in version.materials}

        for m in list(version.materials):
            self.session.delete(m)
        version.materials = []  # Clear logic list

        for m_in in data.materials:
            # Handle lineage_id: validate if provided, generate if not
            if m_in.lineage_id:
                if m_in.lineage_id not in existing_material_lineages:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid material lineage_id: {m_in.lineage_id} does not exist in current version"
                    )
                final_lineage_id = m_in.lineage_id  # Preserve
            else:
                final_lineage_id = uuid.uuid4()  # Generate new for new items

            # Use source_material_definition_id from frontend, or preserve existing if not provided
            source_def_id = m_in.source_material_definition_id
            if not source_def_id and m_in.lineage_id and m_in.lineage_id in existing_material_definitions:
                # Fallback: preserve existing if frontend didn't provide one
                source_def_id = existing_material_definitions.get(
                    m_in.lineage_id)

            self.session.add(ProductVersionMaterial(
                version_id=version.id,
                lineage_id=final_lineage_id,
                # Use from frontend or preserve existing
                source_material_definition_id=source_def_id,
                material_name=m_in.name,
                percentage=m_in.percentage,
                origin_country=m_in.origin_country,
                transport_method=m_in.transport_method
            ))

        # 3. Update Supply Chain (Full Replace Strategy with Lineage Tracking)
        existing_supply_lineages = {s.lineage_id for s in version.supply_chain}

        for s in list(version.supply_chain):
            self.session.delete(s)
        version.supply_chain = []

        for s_in in data.sub_suppliers:
            # Handle lineage_id
            if s_in.lineage_id:
                if s_in.lineage_id not in existing_supply_lineages:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid supply node lineage_id: {s_in.lineage_id} does not exist in current version"
                    )
                final_lineage_id = s_in.lineage_id
            else:
                final_lineage_id = uuid.uuid4()

            self.session.add(ProductVersionSupplyNode(
                version_id=version.id,
                lineage_id=final_lineage_id,
                role=s_in.role,
                company_name=s_in.name,
                location_country=s_in.country
            ))

        # 4. Handle Certificates (with Lineage Tracking)
        # Map uploaded files by their internal ID from the frontend (temp_file_id)
        file_map = {f.filename: f for f in files}

        # Build map of existing lineage IDs for validation and preserve existing data (similar to materials)
        existing_cert_lineages = {c.lineage_id for c in version.certificates}
        existing_cert_type_ids = {
            c.lineage_id: c.certificate_type_id for c in version.certificates}
        existing_cert_issuers = {
            c.lineage_id: c.snapshot_issuer for c in version.certificates}
        existing_cert_artifacts = {
            c.lineage_id: c.source_artifact_id for c in version.certificates}
        existing_cert_file_names = {
            c.lineage_id: c.file_name for c in version.certificates}
        existing_cert_file_types = {
            c.lineage_id: c.file_type for c in version.certificates}
        existing_cert_file_sizes = {
            c.lineage_id: c.file_size_bytes for c in version.certificates}
        # Preserve existing certificate type (can be from library or manually entered)
        existing_cert_types = {
            c.lineage_id: _get_certificate_type_value(c) for c in version.certificates}

        # Fetch all certificate definitions (full objects, not just issuer_authority)
        cert_type_ids = list(
            {cert_input.certificate_type_id for cert_input in data.certificates if cert_input.certificate_type_id})
        cert_definitions = {}  # Will store full CertificateDefinition objects
        if cert_type_ids:
            cert_defs = self.session.exec(
                select(CertificateDefinition)
                .where(CertificateDefinition.id.in_(cert_type_ids))
            ).all()
            cert_definitions = {cd.id: cd for cd in cert_defs}
            
            # Log warning if any certificate definitions are missing
            found_ids = {cd.id for cd in cert_defs}
            missing_ids = set(cert_type_ids) - found_ids
            if missing_ids:
                logger.warning(f"Certificate definitions not found for IDs: {missing_ids}")

        # Clear existing certificate links
        # (We recreate them to ensure the list matches the frontend state exactly)
        for old_cert in list(version.certificates):
            self.session.delete(old_cert)
        version.certificates = []

        for cert_input in data.certificates:
            # Handle certificate_type_id: 
            # - If provided, use it (from library)
            # - If None but certificate_type is provided, use manual entry (don't preserve old certificate_type_id)
            # - If both None, preserve existing (for updates where frontend didn't change the selection)
            final_cert_type_id = cert_input.certificate_type_id
            
            # Only preserve existing certificate_type_id if:
            # 1. certificate_type_id is not provided (None)
            # 2. certificate_type is also not provided (None) - meaning frontend didn't change anything
            # 3. There's an existing certificate with this lineage_id
            if final_cert_type_id is None and cert_input.certificate_type is None and cert_input.lineage_id and cert_input.lineage_id in existing_cert_type_ids:
                # Preserve existing certificate_type_id when frontend didn't provide either field
                final_cert_type_id = existing_cert_type_ids.get(cert_input.lineage_id)

            # Validate certificate definition exists if certificate_type_id is provided
            cert_def = None
            if final_cert_type_id:
                if final_cert_type_id not in cert_definitions:
                    # Try to fetch it individually to get better error message
                    cert_def = self.session.get(CertificateDefinition, final_cert_type_id)
                    if not cert_def:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Certificate definition with ID {final_cert_type_id} not found. Please ensure the certificate type exists."
                        )
                    cert_definitions[final_cert_type_id] = cert_def
                else:
                    cert_def = cert_definitions[final_cert_type_id]

            # Determine certificate type: from definition if certificate_type_id provided, else from manual input or existing
            # Similar to material_name - we only store the type, not code/category/description
            if cert_def:
                # Use certificate definition to populate certificate type (from library)
                cert_type = cert_def.name
                final_issuer = cert_def.issuer_authority if cert_def.issuer_authority and cert_def.issuer_authority.strip() else "Unknown"
            elif cert_input.certificate_type:
                # Manual entry: use provided type (for unlisted certificates or when changing from library to manual)
                cert_type = cert_input.certificate_type
                # For manual entry, issuer can be provided or use existing
                final_issuer = cert_input.issuer if cert_input.issuer else (
                    existing_cert_issuers.get(cert_input.lineage_id) if cert_input.lineage_id and cert_input.lineage_id in existing_cert_issuers else "Unknown"
                )
            elif cert_input.lineage_id and cert_input.lineage_id in existing_cert_types:
                # Preserve existing certificate type if updating and no new value provided
                cert_type = existing_cert_types[cert_input.lineage_id]
                final_issuer = existing_cert_issuers.get(cert_input.lineage_id) if cert_input.lineage_id in existing_cert_issuers else "Unknown"
            else:
                # Validation: must have either certificate_type_id OR certificate_type
                raise HTTPException(
                    status_code=400,
                    detail="Either certificate_type_id must be provided (to select from library), or certificate_type must be provided (for manual entry of unlisted certificates)."
                )
            
            # Handle lineage_id
            if cert_input.lineage_id:
                if cert_input.lineage_id not in existing_cert_lineages:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid certificate lineage_id: {cert_input.lineage_id} does not exist in current version"
                    )
                final_lineage_id = cert_input.lineage_id
            else:
                final_lineage_id = uuid.uuid4()

            final_file_url = cert_input.file_url
            artifact_id = None
            detected_content_type = "application/octet-stream"
            final_file_name = None  # Will be set in either CASE A or CASE B
            final_file_size_bytes = None  # Will be set in either CASE A or CASE B

            # CASE A: NEW FILE UPLOAD
            if cert_input.temp_file_id and cert_input.temp_file_id in file_map:
                uploaded_file = file_map[cert_input.temp_file_id]

                print("The uploaded file details: ",
                      uploaded_file.content_type, uploaded_file.filename)

                # Validate file extension for certificates
                from app.utils.file_storage import validate_certificate_file_extension
                validate_certificate_file_extension(uploaded_file.filename or "")

                # Capture file size before saving
                # Read the file content to get size (we need to do this before saving)
                uploaded_file.file.seek(0, 2)  # Seek to end
                file_size = uploaded_file.file.tell()
                uploaded_file.file.seek(0)  # Reset to beginning for saving
                final_file_size_bytes = file_size

                # Detect MIME
                if uploaded_file.content_type:
                    detected_content_type = uploaded_file.content_type
                else:
                    mime, _ = mimetypes.guess_type(uploaded_file.filename)
                    if mime:
                        detected_content_type = mime

                # Save to S3/Local (validate_extension=False since we already validated above)
                saved_url = save_upload_file(uploaded_file, validate_extension=False)

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
                artifact_id = artifact.id  # Use new artifact for new upload
                # Use the original filename with extension for file_name
                final_file_name = uploaded_file.filename

            # CASE B: EXISTING FILE (NO NEW UPLOAD)
            elif final_file_url:
                # Use source_artifact_id from frontend (the file/artifact from supplier's library), or preserve existing if not provided
                artifact_id = cert_input.source_artifact_id
                if not artifact_id and cert_input.lineage_id and cert_input.lineage_id in existing_cert_artifacts:
                    # Fallback: preserve existing artifact/file link if frontend didn't provide one
                    artifact_id = existing_cert_artifacts[cert_input.lineage_id]

                # Preserve existing file_name and file_type if updating an existing certificate
                # Frontend can optionally provide file_name to update it, otherwise preserve existing
                if cert_input.lineage_id and cert_input.lineage_id in existing_cert_file_names:
                    # Preserve existing file_name (with extension) unless frontend explicitly provides a new one
                    final_file_name = cert_input.file_name if cert_input.file_name else existing_cert_file_names[cert_input.lineage_id]
                    # Preserve existing file_type unless we can detect a better one
                    if cert_input.lineage_id in existing_cert_file_types:
                        detected_content_type = existing_cert_file_types[cert_input.lineage_id]
                else:
                    # New certificate from library - use file_name from frontend or extract from URL
                    final_file_name = cert_input.file_name or final_file_url.split("/")[-1]
                
                # Guess Type for Snapshot (only if we don't have existing file_type)
                if not (cert_input.lineage_id and cert_input.lineage_id in existing_cert_file_types):
                    mime, _ = mimetypes.guess_type(final_file_url)
                    if mime:
                        detected_content_type = mime

            # Create Link (Snapshot)
            if final_file_url:
                # Ensure file_name is set (fallback to extracting from URL if not set)
                if final_file_name is None:
                    final_file_name = cert_input.file_name or final_file_url.split("/")[-1]

                # Validate cert_type is set (should be set above, but double-check)
                if not cert_type:
                    raise HTTPException(
                        status_code=400,
                        detail="certificate_type is required. Either provide certificate_type_id or certificate_type manually."
                    )

                new_link = ProductVersionCertificate(
                    version_id=version.id,
                    lineage_id=final_lineage_id,
                    certificate_type_id=final_cert_type_id,  # Use preserved/validated certificate_type_id (None if manually entered)
                    # Link to the SupplierArtifact (file) that was used - either from library selection or newly uploaded
                    source_artifact_id=artifact_id,
                    snapshot_name=cert_input.name,
                    snapshot_issuer=final_issuer,
                    # Certificate type (from library or manually entered)
                    # Similar to material_name - we only store the type, not code/category/description
                    certificate_type=cert_type,
                    valid_until=cert_input.expiry_date,
                    file_url=final_file_url,
                    file_name=final_file_name,  # Preserve original filename with extension
                    file_type=detected_content_type,
                    file_size_bytes=final_file_size_bytes  # File size in bytes
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
        STRATEGY: 
        1. Always create a NEW version (Sequence + 1).
        2. Source data MUST come from the latest APPROVED version.
        3. If no APPROVED version exists (e.g. first run was cancelled), start FRESH/EMPTY.
        """
        brand = self._get_brand_context(user)

        # 1. Fetch Context
        product = self.session.get(Product, product_id)
        if not product or product.tenant_id != brand.id:
            raise HTTPException(status_code=404, detail="Product not found.")

        profile = self.session.get(SupplierProfile, data.supplier_profile_id)
        if not profile or profile.tenant_id != brand.id:
            raise HTTPException(
                status_code=404, detail="Supplier profile not found.")

        connection = profile.connection
        if not connection or connection.status != ConnectionStatus.ACTIVE or not connection.target_tenant_id:
            raise HTTPException(
                status_code=400, detail="Supplier connection is not active.")

        real_supplier_id = connection.target_tenant_id

        # 2. Analyze Existing Versions
        all_versions = self.session.exec(
            select(ProductVersion)
            .where(ProductVersion.product_id == product.id)
            .order_by(ProductVersion.version_sequence.desc())
        ).all()

        target_version = None

        # Determine the next sequence number
        if not all_versions:
            next_sequence = 1
        else:
            # Always increment based on the absolute latest (even if it was cancelled)
            # This preserves the unique history of the database rows.
            latest_any_status = all_versions[0]
            next_sequence = latest_any_status.version_sequence + 1

            # BLOCKING CHECK: Is the HEAD version currently active?
            # We can't start a new workflow if the previous one is still pending.
            active_statuses = [
                RequestStatus.SENT, RequestStatus.ACCEPTED,
                RequestStatus.IN_PROGRESS, RequestStatus.CHANGES_REQUESTED,
                RequestStatus.SUBMITTED
            ]

            active_req = self.session.exec(
                select(ProductContributionRequest)
                .where(ProductContributionRequest.current_version_id == latest_any_status.id)
                .where(ProductContributionRequest.status.in_(active_statuses))
            ).first()

            if active_req:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot assign: The latest version has an active request ({active_req.status.value}). Please Cancel or Review it first."
                )

        # 3. Find the 'Golden Master' (Latest APPROVED version)
        # We search through history to find the last known good state.
        latest_approved = next(
            (v for v in all_versions if v.status == ProductVersionStatus.APPROVED), None)

        if latest_approved:
            # SCENARIO A: We have a valid history. CLONE it.
            # This ensures we don't propagate 'Rejected' or 'Cancelled' bad data.
            target_version = self._deep_clone_version(
                source_version=latest_approved,
                new_version_sequence=next_sequence,
                new_status=ProductVersionStatus.DRAFT,
                new_revision=0,  # Reset revision for new major version
                version_name=data.version_name  # Use brand-provided version name
            )
        else:
            # SCENARIO B: No Approved history exists.
            # This handles:
            # 1. Very first assignment (all_versions is empty)
            # 2. Previous attempt was Cancelled/Rejected before Approval (all_versions exists, but none Approved)

            # We create a FRESH, EMPTY version with brand-provided version name.
            target_version = ProductVersion(
                product_id=product.id,
                supplier_tenant_id=real_supplier_id,
                version_sequence=next_sequence,
                revision=0,
                version_name=data.version_name,  # Use brand-provided version name
                status=ProductVersionStatus.DRAFT
                # Note: No data fields copied. Supplier starts from scratch.
            )

        # 4. Finalize Target Version Setup
        # (Deep clone helper might not set these if we used it, or fresh constr set them above)
        # We explicitly enforce them here to be safe.
        target_version.product_id = product.id
        target_version.supplier_tenant_id = real_supplier_id
        target_version.version_sequence = next_sequence

        self.session.add(target_version)
        self.session.flush()

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

        # 6. Add Note
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
            .where(ProductVersion.status == ProductVersionStatus.APPROVED)
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
                lineage_id=m.lineage_id,
                material_name=m.material_name,
                percentage=m.percentage,
                origin_country=m.origin_country,
                transport_method=m.transport_method
            ) for m in version.materials],

            supply_chain=[ProductSupplyNodeRead(
                id=s.id,
                lineage_id=s.lineage_id,
                role=s.role,
                company_name=s.company_name,
                location_country=s.location_country
            ) for s in version.supply_chain],

            certificates=[ProductCertificateRead(
                id=c.id,
                lineage_id=c.lineage_id,
                certificate_type_id=c.certificate_type_id,
                snapshot_name=c.snapshot_name,
                snapshot_issuer=c.snapshot_issuer,
                certificate_type=_get_certificate_type_value(c),
                valid_until=c.valid_until,
                file_url=c.file_url,
                file_type=c.file_type,
                file_size_bytes=c.file_size_bytes
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

        # 1. Fetch Latest Version (Sort by Sequence AND Revision)
        version = self.session.exec(
            select(ProductVersion)
            .where(ProductVersion.product_id == product_id)
            .order_by(
                ProductVersion.version_sequence.desc(),
                ProductVersion.revision.desc()
            )
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

        # 2. Get latest request associated with this specific version snapshot
        request = self.session.exec(
            select(ProductContributionRequest)
            .where(ProductContributionRequest.current_version_id == version.id)
            .where(ProductContributionRequest.brand_tenant_id == brand.id)
            .order_by(ProductContributionRequest.created_at.desc())
            .options(selectinload(ProductContributionRequest.comments))
        ).first()

        supplier_name = None
        supplier_country = None
        supplier_profile_id = None
        due_date = None
        req_status = None
        req_id = None
        req_updated_at = None
        decline_reason = None

        if request:
            req_id = request.id
            req_status = request.status
            due_date = request.due_date
            req_updated_at = request.updated_at

            # Resolve Supplier Info via Profile (Preferred) or Tenant
            if request.connection_id:
                profile = self.session.exec(
                    select(SupplierProfile)
                    .where(SupplierProfile.connection_id == request.connection_id)
                    .where(SupplierProfile.tenant_id == brand.id)
                ).first()

                if profile:
                    supplier_profile_id = profile.id
                    supplier_name = profile.name  # Brand's alias
                    supplier_country = profile.location_country

            # Fallback to raw tenant if no profile (shouldn't happen in stricter flows but safe)
            if not supplier_name:
                supplier = self.session.get(Tenant, request.supplier_tenant_id)
                if supplier:
                    supplier_name = supplier.name
                    supplier_country = supplier.location_country

            # Fetch decline reason if request is declined
            if req_status == RequestStatus.DECLINED and request.comments:
                # Find the decline reason comment from supplier (most recent one)
                supplier_tenant_id = request.supplier_tenant_id
                # Sort comments by date descending to get most recent first
                sorted_comments = sorted(
                    request.comments, key=lambda c: c.created_at, reverse=True)
                for comment in sorted_comments:
                    # Check if comment author belongs to supplier tenant
                    comment_author = self.session.get(
                        User, comment.author_user_id)
                    if comment_author:
                        author_membership = self.session.exec(
                            select(TenantMember)
                            .where(TenantMember.user_id == comment_author.id)
                            .where(TenantMember.status == MemberStatus.ACTIVE)
                        ).first()
                        if author_membership and author_membership.tenant_id == supplier_tenant_id:
                            # This is the decline reason from supplier (most recent supplier comment)
                            decline_reason = comment.body
                            break

        return ProductCollaborationStatusRead(
            active_request_id=req_id,
            product_id=product.id,
            latest_version_id=version.id,
            request_status=req_status,
            version_status=version.status,
            assigned_supplier_name=supplier_name,
            assigned_supplier_profile_id=supplier_profile_id,
            supplier_country=supplier_country,
            due_date=due_date,
            last_updated_at=req_updated_at if req_updated_at else version.updated_at,
            decline_reason=decline_reason
        )

    def cancel_request(self, user: User, product_id: uuid.UUID, request_id: uuid.UUID, reason: str):
        brand = self._get_brand_context(user)

        request = self.session.get(ProductContributionRequest, request_id)
        if not request or request.brand_tenant_id != brand.id:
            raise HTTPException(status_code=404, detail="Request not found.")

        # 1. STRICT REQUEST GUARD
        # We include SUBMITTED here. If it's submitted, Brand must Review, not Cancel.
        if request.status in [RequestStatus.SUBMITTED, RequestStatus.COMPLETED, RequestStatus.CANCELLED]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel request. Current status is '{request.status.value}'. If Submitted, please Review instead."
            )

        # 2. STRICT VERSION GUARD
        # Fetch the version this request is pointing to
        version = self.session.get(ProductVersion, request.current_version_id)
        if not version:
            raise HTTPException(
                status_code=404, detail="Associated product version not found.")

        # Detect Data Conflict: Request says it's editable, but Version says it's locked.
        if version.status in [ProductVersionStatus.SUBMITTED, ProductVersionStatus.APPROVED]:
            raise HTTPException(
                status_code=409,  # Conflict
                detail=f"Data Integrity Error: The request is '{request.status.value}' but the technical data is already '{version.status.value}'. Please refresh or contact support."
            )

        # 3. EXECUTE CANCELLATION
        request.status = RequestStatus.CANCELLED

        # 4. INVALIDATE VERSION
        # If it was Draft (Work in progress) or Rejected (Supplier declined),
        # we mark it Cancelled to indicate this specific snapshot is dead.
        if version.status in [ProductVersionStatus.DRAFT, ProductVersionStatus.REJECTED]:
            version.status = ProductVersionStatus.CANCELLED
            self.session.add(version)

        # 5. Add Comment/Audit
        self.session.add(CollaborationComment(
            request_id=request.id,
            author_user_id=user.id,
            body=f"Request Cancelled: {reason}",
            is_rejection_reason=True
        ))

        self.session.add(request)
        self.session.commit()

        return {"message": "Request cancelled successfully."}

    def review_submission(self, user: User, product_id: uuid.UUID, request_id: uuid.UUID, action: str, comment: Optional[str] = None):
        """
        Brand Action: Approve or Request Changes.
        """
        brand = self._get_brand_context(user)

        request = self.session.get(ProductContributionRequest, request_id)
        if not request or request.brand_tenant_id != brand.id:
            raise HTTPException(status_code=404, detail="Request not found.")

        # Determine Version
        version = self.session.get(ProductVersion, request.current_version_id)

        if action == "approve":
            request.status = RequestStatus.COMPLETED
            version.status = ProductVersionStatus.APPROVED

            # Update Product Updated At
            if version.product_id:
                product = self.session.get(Product, version.product_id)
                product.updated_at = datetime.now(timezone.utc)
                self.session.add(product)

        elif action == "request_changes":
            request.status = RequestStatus.CHANGES_REQUESTED
            version.status = ProductVersionStatus.REJECTED  # Mark old as Rejected

            # Require comment when requesting changes
            if not comment or not comment.strip():
                raise HTTPException(
                    status_code=400,
                    detail="A comment is required when requesting changes. Please provide feedback to the supplier."
                )

            # Create New Revision (Clone)
            new_draft = self._deep_clone_version(
                source_version=version,
                new_version_sequence=version.version_sequence,
                new_status=ProductVersionStatus.DRAFT,
                new_revision=version.revision + 1
            )

            # Switch Request to point to new Draft
            request.current_version_id = new_draft.id
            self.session.add(new_draft)

        else:
            raise HTTPException(status_code=400, detail="Invalid action.")

        # Add Comment (required for request_changes, optional for approve)
        if comment and comment.strip():
            self.session.add(CollaborationComment(
                request_id=request.id,
                author_user_id=user.id,
                body=comment.strip(),
                is_rejection_reason=(action == "request_changes")
            ))

        self.session.add(request)
        self.session.add(version)
        self.session.commit()

        return {"message": f"Submission {action}d successfully."}

    def _map_version_to_snapshot(self, version: ProductVersion) -> VersionComparisonSnapshot:
        """
        Helper: Flattens a ProductVersion into a Comparison Snapshot.
        """
        if not version:
            return None

        # IMPACT
        impacts = []
        if version.total_carbon_footprint:
            impacts.append(VersionComparisonImpact(
                id="carbon", label="Carbon Footprint", val=f"{version.total_carbon_footprint} kg CO2e"
            ))
        if version.total_water_usage:
            impacts.append(VersionComparisonImpact(
                id="water", label="Water Usage", val=f"{version.total_water_usage} L"
            ))
        if version.total_energy_mj:
            impacts.append(VersionComparisonImpact(
                id="energy", label="Energy Usage", val=f"{version.total_energy_mj} MJ"
            ))
        if version.mass_kg:
            impacts.append(VersionComparisonImpact(
                id="mass", label="Net Weight", val=f"{version.mass_kg} kg"
            ))

        return VersionComparisonSnapshot(
            version_sequence=version.version_sequence,
            revision=version.revision or 0,
            version_label=f"{version.version_name} ({version.status.value})",
            materials=[
                VersionComparisonMaterial(
                    id=m.id,
                    lineage_id=m.lineage_id,
                    material_name=m.material_name,
                    percentage=m.percentage,
                    origin_country=m.origin_country,
                    transport_method=m.transport_method
                ) for m in version.materials
            ],
            supply_chain=[
                VersionComparisonSupply(
                    id=s.id,
                    lineage_id=s.lineage_id,
                    role=s.role,
                    company_name=s.company_name,
                    location_country=s.location_country
                ) for s in version.supply_chain
            ],
            impact=impacts,
            certificates=[
                VersionComparisonCertificate(
                    id=c.id,
                    lineage_id=c.lineage_id,
                    certificate_type_id=c.certificate_type_id,
                    snapshot_name=c.snapshot_name,
                    snapshot_issuer=c.snapshot_issuer,
                    certificate_type=_get_certificate_type_value(c),
                    valid_until=c.valid_until,
                    file_url=c.file_url,
                    file_type=c.file_type,
                    file_size_bytes=c.file_size_bytes
                ) for c in version.certificates
            ]
        )

    def compare_request_versions(
        self,
        user: User,
        product_id: uuid.UUID,
        request_id: uuid.UUID,
        compare_to: Optional[uuid.UUID] = None
    ) -> VersionComparisonResponse:
        """
        Compares the request's current version against a previous version.
        """
        # 1. Validation
        brand = self._get_brand_context(user)
        req = self.session.get(ProductContributionRequest, request_id)
        if not req or req.brand_tenant_id != brand.id:
            raise HTTPException(status_code=404, detail="Request not found.")

        # 2. Fetch Current Version (Eager Load everything)
        current_v = self.session.exec(
            select(ProductVersion)
            .where(ProductVersion.id == req.current_version_id)
            .options(
                selectinload(ProductVersion.materials),
                selectinload(ProductVersion.supply_chain),
                selectinload(ProductVersion.certificates)
            )
        ).first()

        if not current_v:
            raise HTTPException(
                status_code=404, detail="Current version not found.")

        # 3. Fetch Previous Version
        previous_v = None
        if compare_to:
            previous_v = self.session.exec(
                select(ProductVersion)
                .where(ProductVersion.id == compare_to)
                .options(
                    selectinload(ProductVersion.materials),
                    selectinload(ProductVersion.supply_chain),
                    selectinload(ProductVersion.certificates)
                )
            ).first()

        # 4. Map Response
        return VersionComparisonResponse(
            current=self._map_version_to_snapshot(current_v),
            previous=self._map_version_to_snapshot(
                previous_v) if previous_v else None
        )
