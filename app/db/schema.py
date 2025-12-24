from typing import Optional, List, Dict, Any
from datetime import datetime, date
import uuid
from sqlmodel import SQLModel, Field, Relationship, JSON
from enum import Enum


class TenantType(str, Enum):
    BRAND = "brand"        # e.g., UK Brand
    SUPPLIER = "supplier"  # e.g., PK Manufacturer
    HYBRID = "hybrid"


class TenantStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class VersionStatus(str, Enum):
    WORKING_DRAFT = "working_draft"   # Editable by Supplier
    SUBMITTED = "submitted"           # Locked, waiting for Brand
    REVISION_REQUIRED = "revision_req"  # Brand rejected, Supplier must fix
    APPROVED = "approved"             # Locked, ready for Passport
    PUBLISHED = "published"           # Live
    ARCHIVED = "archived"


class RequestStatus(str, Enum):
    SENT = "sent"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    CHANGES_REQUESTED = "changes_req"
    COMPLETED = "completed"


class MaterialType(str, Enum):
    COTTON = "cotton"
    POLYESTER = "polyester"
    NYLON = "nylon"
    WOOL = "wool"
    VISCOSE = "viscose"
    BLEND = "blend"
    OTHER = "other"


class SupplierRole(str, Enum):
    TIER_1_ASSEMBLY = "tier_1_assembly"  # Final Cut & Sew
    TIER_2_FABRIC = "tier_2_fabric"     # Fabric Mill
    TIER_3_FIBER = "tier_3_fiber"       # Raw Fiber


class DPPStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    SUSPENDED = "suspended"


class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"


class MemberStatus(str, Enum):
    """Controls access at the specific Tenant level."""
    ACTIVE = "active"
    INACTIVE = "inactive"


class ConnectionStatus(str, Enum):
    PENDING = "pending"           # Invite sent, waiting for Supplier to accept
    CONNECTED = "connected"       # Handshake complete, can assign Requests
    DECLINED = "declined"         # Supplier rejected the connection
    DISCONNECTED = "disconnected"  # Relationship ended by either party


class TimestampMixin(SQLModel):
    """
    A foundational mixin that provides standard audit timestamps for database records.
    This ensures that every entity inheriting from this mixin tracks when it was 
    originally created and when it was last modified, which is crucial for data 
    integrity and history tracking.
    """
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="The exact UTC timestamp when this record was first persisted in the database. Example: '2023-10-27 14:30:00'"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
        description="The exact UTC timestamp when this record was last modified. Updates automatically. Example: '2023-10-28 09:15:00'"
    )


class RolePermissionLink(TimestampMixin, SQLModel, table=True):
    """
    A many-to-many pivot table connecting Roles to Permissions.
    This table resolves the relationship that allows a single Role (e.g., 'Admin')
    to hold multiple Permissions (e.g., 'create_user', 'delete_product'), and 
    a single Permission to belong to multiple Roles.
    """
    role_id: uuid.UUID = Field(
        foreign_key="role.id",
        primary_key=True,
        description="The UUID of the role being assigned permissions. Example: '550e8400-e29b-41d4-a716-446655440000'"
    )
    permission_id: uuid.UUID = Field(
        foreign_key="permission.id",
        primary_key=True,
        description="The UUID of the specific permission being granted. Example: 'a1b2c3d4-e5f6-7890-1234-567890abcdef'"
    )


class Permission(TimestampMixin, SQLModel, table=True):
    """
    Represents an atomic authorization unit or capability within the system.
    Permissions are hard-coded or system-defined actions that determine what 
    a user is allowed to do (e.g., 'product:create', 'request:approve'). 
    These are linked to Roles, never directly to Users.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="The unique identifier for this permission."
    )
    key: str = Field(
        unique=True,
        index=True,
        description="The technical slug used in code checks to verify authorization. Example: 'dpp:publish'"
    )
    description: Optional[str] = Field(
        default=None,
        description="A human-readable explanation of what this permission allows. Example: 'Allows the user to publish a Digital Product Passport to the public.'"
    )

    roles: List["Role"] = Relationship(
        back_populates="permissions", link_model=RolePermissionLink)


class Role(TimestampMixin, SQLModel, table=True):
    """
    Represents a named collection of permissions.
    Roles can be Global (system-defined, available to all tenants) or Custom 
    (scoped to a specific Tenant). Users are assigned a Role when they are 
    added to a Tenant via the TenantMember table.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="The unique identifier for this role."
    )
    tenant_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="tenant.id",
        description="If set, this role is custom and only available within this specific Tenant. If NULL, it is a System Global role. Example: 'c7c8f02b-23e9-4e0d-b8d1-72120033c46a'"
    )

    name: str = Field(
        index=True,
        description="The display name of the role. Example: 'Supply Chain Manager'"
    )
    description: Optional[str] = Field(
        default=None,
        description="Details about the responsibilities associated with this role. Example: 'Can manage suppliers and approve data requests.'"
    )

    permissions: List["Permission"] = Relationship(
        back_populates="roles", link_model=RolePermissionLink)
    memberships: List["TenantMember"] = Relationship(back_populates="role")
    tenant: Optional["Tenant"] = Relationship(back_populates="custom_roles")


class Tenant(TimestampMixin, SQLModel, table=True):
    """
    Represents an Organization, Company, or Workspace within the platform.
    This is the top-level container for all business data. A Tenant can be a 
    Brand (data requester) or a Supplier (data provider). All products, 
    connections, and members belong to a Tenant.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="The unique identifier for the Organization."
    )
    name: str = Field(
        index=True,
        description="The legal or display name of the organization. Example: 'Acme Clothing Co.'"
    )
    slug: str = Field(
        unique=True,
        index=True,
        description="A URL-friendly identifier for the organization, often used in subdomains or deep links. Example: 'acme-clothing'"
    )
    type: TenantType = Field(
        default=TenantType.BRAND,
        description="Categorizes the business logic for this tenant (Brand vs Supplier). Example: 'brand'"
    )
    status: TenantStatus = Field(
        default=TenantStatus.ACTIVE,
        description="The operational status of the account. Example: 'active'"
    )

    # very important for supplier
    location_country: str = Field(description="ISO 2-letter country code.")

    # Relationships
    members: List["TenantMember"] = Relationship(back_populates="tenant")
    custom_roles: List["Role"] = Relationship(back_populates="tenant")
    invitations: List["TenantInvitation"] = Relationship(
        back_populates="tenant")

    # Ownership
    products: List["Product"] = Relationship(back_populates="tenant")
    supplier_profiles: List["SupplierProfile"] = Relationship(
        back_populates="tenant",
        sa_relationship_kwargs={"foreign_keys": "[SupplierProfile.tenant_id]"}
    )
    custom_materials: List["Material"] = Relationship(back_populates="tenant")

    # Passport Extras
    dpp_extra_details: List["DPPExtraDetail"] = Relationship(
        back_populates="tenant")


class User(TimestampMixin, SQLModel, table=True):
    """
    Represents a Global Human User in the system.
    A user exists independently of any organization. They can belong to 
    multiple Tenants (e.g., a Consultant working for multiple Brands) via 
    the TenantMember association table.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="The unique identifier for the user."
    )
    email: str = Field(
        unique=True,
        index=True,
        description="The login email address. Example: 'john.doe@example.com'"
    )
    hashed_password: str = Field(
        description="The securely salted and hashed password string. Never store plain text. Example: '$2b$12$EixZaYVK1fsdf31...'"
    )
    first_name: str = Field(
        description="The user's first name. Example: 'John'"
    )
    last_name: str = Field(
        description="The user's last name. Example: 'Doe'"
    )
    is_active: bool = Field(
        default=True,
        description="Soft delete flag. If False, user cannot log in. Example: True"
    )

    memberships: List["TenantMember"] = Relationship(back_populates="user")

    sent_invitations: List["TenantInvitation"] = Relationship(
        back_populates="inviter",
        sa_relationship_kwargs={
            "foreign_keys": "[TenantInvitation.inviter_id]"}
    )
    received_invitations: List["TenantInvitation"] = Relationship(
        back_populates="invitee",
        sa_relationship_kwargs={
            "foreign_keys": "[TenantInvitation.invitee_id]"}
    )


class TenantMember(TimestampMixin, SQLModel, table=True):
    """
    The Association link between a User and a Tenant.
    This defines 'Who belongs to Which Organization' and 'What Role they have 
    in that Organization'. A user cannot act within a tenant without this record.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="The unique ID of this membership record."
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id",
        index=True,
        description="The Organization the user is being linked to."
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id",
        index=True,
        description="The User being linked."
    )

    role_id: uuid.UUID = Field(
        foreign_key="role.id",
        description="The Role assigned to this user specifically for this context/tenant."
    )

    status: MemberStatus = Field(
        default=MemberStatus.ACTIVE,
        description="Current status of the member within the org (e.g., Active or Inactive). Example: 'active'"
    )

    tenant: Tenant = Relationship(back_populates="members")
    user: User = Relationship(back_populates="memberships")
    role: Role = Relationship(back_populates="memberships")


class TenantInvitation(TimestampMixin, SQLModel, table=True):
    """
    Represents a pending invitation to join a Tenant.
    Used for onboarding. It stores the security token sent via email and 
    tracks the status of the invite before a User/TenantMember record is fully established.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique identifier for the invitation."
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id",
        description="The target workspace/organization the user is invited to."
    )
    email: str = Field(
        index=True,
        description="The email address the invitation was sent to. Example: 'new.hire@acme.com'"
    )
    token: str = Field(
        unique=True,
        description="A unique, high-entropy string included in the email link to verify the invite. Example: 'abc123xyz...'"
    )
    status: InvitationStatus = Field(
        default=InvitationStatus.PENDING,
        description="Current state of the invite. Example: 'pending'"
    )
    expires_at: datetime = Field(
        description="The timestamp when this invitation link becomes invalid. Example: '2025-12-31 23:59:59'"
    )

    role_id: uuid.UUID = Field(
        foreign_key="role.id",
        description="The role the user will automatically receive upon acceptance. Example: 'Viewer Role ID'"
    )

    # Actors
    inviter_id: uuid.UUID = Field(
        foreign_key="user.id",
        description="The existing member (User ID) who initiated the invite."
    )
    invitee_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="user.id",
        description="The receiver's User ID, if they already exist in the system. Null if they are a brand new user."
    )

    tenant: Tenant = Relationship(back_populates="invitations")

    inviter: "User" = Relationship(
        back_populates="sent_invitations",
        sa_relationship_kwargs={"foreign_keys": "TenantInvitation.inviter_id"}
    )

    invitee: Optional["User"] = Relationship(
        back_populates="received_invitations",
        sa_relationship_kwargs={"foreign_keys": "TenantInvitation.invitee_id"}
    )


class TenantConnection(TimestampMixin, SQLModel, table=True):
    """
    Represents the handshake state.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    brand_tenant_id: uuid.UUID = Field(foreign_key="tenant.id", index=True)
    supplier_tenant_id: Optional[uuid.UUID] = Field(
        foreign_key="tenant.id", default=None)

    # The Link
    supplier_profile_id: uuid.UUID = Field(
        foreign_key="supplierprofile.id",
        unique=True  # Enforces 1:1
    )

    # Audit / Transactional Field
    supplier_email_invite: Optional[str] = Field(
        default=None,
        description="If invited via email, this stores the target address for audit/retry."
    )

    status: ConnectionStatus = Field(default=ConnectionStatus.PENDING)

    supplier_profile: "SupplierProfile" = Relationship(
        back_populates="connection")


class Material(TimestampMixin, SQLModel, table=True):
    """
    Represents a library definition of a raw material.
    Materials can be System Global (standard ISO definitions) or Tenant Specific 
    (custom proprietary blends defined by a brand).
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique identifier for the material."
    )
    tenant_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="tenant.id",
        description="If Null, this is a System/Global material visible to everyone. If set, it is private to that Tenant."
    )
    name: str = Field(
        index=True,
        description="Common name of the material. Example: 'Organic Cotton'"
    )
    code: str = Field(
        unique=True,
        index=True,
        description="Unique standard code (e.g. ISO code or Internal ERP code). Example: 'MAT-COT-ORG-001'"
    )
    material_type: MaterialType = Field(
        description="High-level categorization of the material. Example: 'cotton'"
    )

    tenant: Optional[Tenant] = Relationship(back_populates="custom_materials")


class Certification(TimestampMixin, SQLModel, table=True):
    """
    Represents globally recognized Standards and Certifications.
    Examples include GOTS, Oeko-Tex Standard 100, Fair Trade, etc.
    These act as the 'types' of certificates that can be uploaded.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique ID for the certification type."
    )
    name: str = Field(
        unique=True,
        description="The official name of the certification standard. Example: 'Global Organic Textile Standard (GOTS)'"
    )
    issuer: str = Field(
        description="The organization or body that governs this standard. Example: 'Global Standard gGmbH'"
    )


class SupplierProfile(TimestampMixin, SQLModel, table=True):
    """
    Represents an entry in a Brand's 'Address Book'.
    Now purely a shell for Display Name + Location + Link to Real Tenant.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id",
        description="The Brand that owns this profile."
    )

    connected_tenant_id: Optional[uuid.UUID] = Field(
        foreign_key="tenant.id",
        default=None,
        description="The Real Supplier Tenant (if connected)."
    )

    name: str = Field(
        description="The Brand's internal alias for this supplier.")
    location_country: str = Field(description="ISO 2-letter country code.")

    # Relationships
    tenant: Tenant = Relationship(
        back_populates="supplier_profiles",
        sa_relationship_kwargs={"foreign_keys": "SupplierProfile.tenant_id"}
    )

    # 1:1 Relationship to the Connection Status
    connection: Optional["TenantConnection"] = Relationship(
        back_populates="supplier_profile",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan", "uselist": False}
    )

    facility_certs: List["SupplierFacilityCertification"] = Relationship(
        back_populates="supplier", sa_relationship_kwargs={"cascade": "all, delete-orphan"})


class SupplierFacilityCertification(TimestampMixin, SQLModel, table=True):
    """
    Represents specific compliance documents held by a Supplier's facility.
    This differs from product certs; this is about the factory itself 
    (e.g., SA8000 Social Accountability, ISO 14001).
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique ID for this document record."
    )
    supplier_profile_id: uuid.UUID = Field(
        foreign_key="supplierprofile.id",
        description="The address book entry this certificate belongs to."
    )
    name: str = Field(
        description="The name of the certificate. Example: 'SA8000 Audit Report'"
    )
    document_url: str = Field(
        description="URL to the stored PDF/Image of the certificate. Example: 'https://s3.bucket/certs/sa8000.pdf'"
    )
    valid_until: Optional[date] = Field(
        default=None,
        description="The expiration date of the certificate. Example: '2026-05-20'"
    )

    supplier: SupplierProfile = Relationship(back_populates="facility_certs")


class Product(TimestampMixin, SQLModel, table=True):
    """
    The Immutable Anchor for a specific item.
    This table represents the high-level identity of a product (SKU, GTIN). 
    It does NOT contain environmental data or supply chain details; those 
    live in 'ProductVersion' to allow for year-over-year changes without 
    changing the core Product ID (and thus breaking the QR code).
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="The persistent unique identifier for the product entity."
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id",
        index=True,
        description="The Brand/Tenant that owns this product."
    )

    sku: str = Field(
        unique=True,
        index=True,
        description="The Stock Keeping Unit, unique internal identifier. Example: 'TSHIRT-BLK-M-001'"
    )
    gtin: Optional[str] = Field(
        default=None,
        description="Global Trade Item Number (EAN/UPC), standard barcode number. Example: '01234567890123'"
    )

    tenant: Tenant = Relationship(back_populates="products")
    versions: List["ProductVersion"] = Relationship(back_populates="product")
    passport: Optional["DigitalProductPassport"] = Relationship(
        back_populates="product")
    spare_parts: List["SparePart"] = Relationship(back_populates="product")


class ProductVersion(TimestampMixin, SQLModel, table=True):
    """
    The Mutable Data Snapshot (The 'Traceability Twin').
    This model contains the actual environmental data, supply chain mapping, 
    and material breakdown. A Product can have multiple versions (e.g., 
    'Spring 2024 Batch' vs 'Fall 2024 Batch'). This record is what gets 
    passed between Suppliers and Brands during the data collection workflow.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique ID for this specific version snapshot."
    )
    product_id: uuid.UUID = Field(
        foreign_key="product.id",
        index=True,
        description="Reference to the parent immutable product."
    )

    # Workflow
    parent_version_id: Optional[uuid.UUID] = Field(
        foreign_key="productversion.id",
        default=None,
        description="If this version was cloned from a previous one, this links to the source. Example: 'uuid-v1'"
    )
    version_number: int = Field(
        default=1,
        description="Incremental integer tracking the iteration count. Example: 2"
    )
    status: VersionStatus = Field(
        default=VersionStatus.WORKING_DRAFT,
        description="The lifecycle state of this data (Draft -> Submitted -> Approved). Example: 'working_draft'"
    )
    created_by_tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id",
        description="The Tenant who initiated this draft. Often the Supplier in a Tier-1 scenario."
    )
    change_note: Optional[str] = Field(
        default=None,
        description="A summary of what changed in this version compared to the last. Example: 'Updated cotton supplier to reduce carbon footprint.'"
    )

    # ENVIRONMENT DATA
    manufacturing_country: str = Field(
        default="PK",
        description="ISO code of the country where final assembly occurred. Example: 'PK'"
    )

    total_carbon_footprint_kg: Optional[float] = Field(
        description="Total CO2 equivalent emissions in KG calculated for 1 unit of this product. Example: 4.5"
    )
    total_water_usage_liters: Optional[float] = Field(
        description="Total water consumption in liters for 1 unit of this product. Example: 250.0"
    )
    total_energy_mj: Optional[float] = Field(
        description="Total energy consumption in Megajoules for 1 unit. Example: 12.5"
    )

    # End of Life
    recycling_instructions: Optional[str] = Field(
        description="Consumer-facing text on how to dispose of the item. Example: 'Remove buttons before recycling.'"
    )
    recyclability_class: Optional[str] = Field(
        description="A classification code indicating ease of recycling. Example: 'Class A'"
    )

    # Display Data
    product_name_display: str = Field(
        description="The marketing name of the product specific to this version. Example: 'Summer Breeze Cotton Tee'"
    )

    # Media
    media_gallery: List[Dict[str, Any]] = Field(
        default_factory=list,
        sa_type=JSON,
        description="A JSON list of media objects (images/videos)."
    )

    # Relationships
    product: Product = Relationship(back_populates="versions")
    materials: List["VersionMaterial"] = Relationship(
        back_populates="version", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    suppliers: List["VersionSupplier"] = Relationship(
        back_populates="version", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    certifications: List["VersionCertification"] = Relationship(
        back_populates="version", sa_relationship_kwargs={"cascade": "all, delete-orphan"})


class VersionMaterial(TimestampMixin, SQLModel, table=True):
    """
    Represents the Material Breakdown (BOM) for a specific Product Version.
    Links the product to the Material Library and defines quantities and 
    sourcing origins.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique ID for this BOM line item."
    )
    version_id: uuid.UUID = Field(
        foreign_key="productversion.id",
        index=True,
        description="The Product Version this material belongs to."
    )

    # Definition
    material_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="material.id",
        description="Link to the standard Material Library. Example: 'uuid-for-cotton'"
    )
    unlisted_material_name: Optional[str] = Field(
        default=None,
        description="Fallback name if the material does not exist in the library. Example: 'Recycled Ocean Plastic X'"
    )
    is_confidential: bool = Field(
        default=False,
        description="If True, this material details should be hidden from public view in the Passport. Example: False"
    )

    # Composition
    percentage: float = Field(
        description="The percentage (0-100) of the total product weight this material represents. Example: 80.0"
    )

    # Sourcing & Impact
    origin_country: str = Field(
        description="ISO code of the country where this raw material was sourced. Example: 'TR'"
    )
    material_carbon_footprint_kg: Optional[float] = Field(
        description="Specific CO2e emissions attribute to procuring/producing just this material component. Example: 1.2"
    )
    transport_method: Optional[str] = Field(
        description="Primary mode of transport for this material to the factory. Example: 'sea'"
    )

    version: ProductVersion = Relationship(back_populates="materials")


class VersionSupplier(TimestampMixin, SQLModel, table=True):
    """
    Represents a node in the Supply Chain Map for a specific Product Version.
    This defines who did what (Tier 1, Tier 2, etc.) for this specific batch.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique ID for this supply chain node."
    )
    version_id: uuid.UUID = Field(
        foreign_key="productversion.id",
        index=True,
        description="The Product Version this supplier contributed to."
    )
    supplier_profile_id: uuid.UUID = Field(
        foreign_key="supplierprofile.id",
        description="Link to the Supplier Address Book entry."
    )
    role: SupplierRole = Field(
        description="The specific function performed by this supplier in the chain. Example: 'tier_1_assembly'"
    )

    version: ProductVersion = Relationship(back_populates="suppliers")


class VersionCertification(TimestampMixin, SQLModel, table=True):
    """
    Represents product-specific certifications or Transaction Certificates (TCs).
    Unlike facility certs, these prove that THIS specific batch of goods 
    complies with a standard (e.g., a GOTS Transaction Certificate for 500 units).
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique ID for this proof."
    )
    version_id: uuid.UUID = Field(
        foreign_key="productversion.id",
        index=True,
        description="The Product Version this certification validates."
    )
    certification_id: Optional[uuid.UUID] = Field(
        foreign_key="certification.id",
        description="Link to the global certification type."
    )
    document_url: str = Field(
        description="URL to the specific Transaction Certificate or proof document. Example: 'https://.../TC-123.pdf'"
    )
    valid_until: Optional[date] = Field(
        default=None,
        description="When this specific proof expires. Example: '2024-12-31'"
    )

    version: ProductVersion = Relationship(back_populates="certifications")


class SparePart(TimestampMixin, SQLModel, table=True):
    """
    Represents Right-to-Repair data associated with a Product.
    Lists parts that can be ordered to extend the product's life.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique ID for the spare part."
    )
    product_id: uuid.UUID = Field(
        foreign_key="product.id",
        description="The parent product this part belongs to."
    )
    name: str = Field(
        description="The common name of the spare part. Example: 'Replacement Zipper'"
    )
    ordering_code: str = Field(
        description="The code used to order this specific part. Example: 'ZIP-YKK-005'"
    )

    product: Product = Relationship(back_populates="spare_parts")


class DataContributionRequest(TimestampMixin, SQLModel, table=True):
    """
    Represents a Work Order or Task sent from a Brand to a Supplier.
    The Brand creates a request asking the Supplier to fill out the 
    'ProductVersion' data for a specific SKU. This model tracks the state 
    of that request.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique ID for this request."
    )
    connection_id: uuid.UUID = Field(
        foreign_key="tenantconnection.id",
        description="The B2B Connection context under which this request is made."
    )

    brand_tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id",
        description="The Requester (Buyer)."
    )
    supplier_tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id",
        description="The Assignee (Manufacturer)."
    )

    # Version Tracking
    initial_version_id: uuid.UUID = Field(
        foreign_key="productversion.id",
        description="The state of the version when the request was first created."
    )
    current_version_id: uuid.UUID = Field(
        foreign_key="productversion.id",
        description="The active version currently being edited/reviewed. Example: 'uuid-v2'"
    )

    status: RequestStatus = Field(
        default=RequestStatus.SENT,
        description="The current processing status of the request. Example: 'in_progress'"
    )

    comments: List["CollaborationComment"] = Relationship(
        back_populates="request")


class CollaborationComment(TimestampMixin, SQLModel, table=True):
    """
    Represents the Chat/Negotiation history regarding a Data Request.
    If a Brand rejects a Supplier's data submission, they leave a comment here 
    explaining why.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique ID for the comment."
    )
    request_id: uuid.UUID = Field(
        foreign_key="datacontributionrequest.id",
        index=True,
        description="The request thread this comment belongs to."
    )

    author_user_id: uuid.UUID = Field(
        foreign_key="user.id",
        description="The user who wrote the comment."
    )

    body: str = Field(
        description="The actual text content of the message. Example: 'Please update the carbon footprint, it looks too low.'"
    )
    is_rejection_reason: bool = Field(
        default=False,
        description="Flag indicating if this comment serves as the official reason for returning a request to the supplier. Example: True"
    )

    request: DataContributionRequest = Relationship(back_populates="comments")


class DigitalProductPassport(TimestampMixin, SQLModel, table=True):
    """
    Represents the Public Facing Digital Twin (DPP).
    This is the entity that the QR code points to. It links to one 'Active' 
    ProductVersion (the data source) and includes display configurations.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique internal ID of the passport."
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id",
        index=True,
        description="The Brand who owns this passport."
    )
    product_id: uuid.UUID = Field(
        foreign_key="product.id",
        unique=True,
        description="The Product this passport represents."
    )

    public_uid: str = Field(
        unique=True,
        index=True,
        description="The public-facing, URL-safe ID used in the QR code link. Example: 'dpp_abc123'"
    )
    status: DPPStatus = Field(
        default=DPPStatus.DRAFT,
        description="Visibility status of the passport. Example: 'published'"
    )

    # Active Pointer
    active_version_id: Optional[uuid.UUID] = Field(
        foreign_key="productversion.id",
        description="The specific approved ProductVersion snapshot that is currently being displayed to consumers. Example: 'uuid-v3-final'"
    )

    # QR & Hosting
    qr_code_image_url: Optional[str] = Field(
        default=None,
        description="The hosted URL of the generated QR code image. Example: 'https://.../qr.png'"
    )
    target_url: str = Field(
        description="The destination URL where the QR code redirects users. Example: 'https://mybrand.com/traceability/dpp_abc123'"
    )
    style_config: Dict[str, Any] = Field(
        default_factory=dict,
        sa_type=JSON,
        description="JSON configuration for frontend styling (colors, logos) of the passport page. Example: {'primary_color': '#FF0000'}"
    )

    product: Product = Relationship(back_populates="passport")
    events: List["DPPEvent"] = Relationship(back_populates="passport")
    extra_details: List["DPPExtraDetail"] = Relationship(
        back_populates="passport", sa_relationship_kwargs={"cascade": "all, delete-orphan"})


class DPPEvent(SQLModel, table=True):
    """
    Represents an Immutable Journey Log / Timeline Event for the Passport.
    These are significant milestones to be displayed on the consumer timeline 
    (e.g., 'Harvested', 'Manufactured', 'Shipped', 'Sold').
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique ID for the event."
    )
    passport_id: uuid.UUID = Field(
        foreign_key="digitalproductpassport.id",
        index=True,
        description="The passport this event is attached to."
    )
    event_type: str = Field(
        description="A categorization of the event. Example: 'manufacturing_completed'"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="The time the event occurred. Example: '2023-11-01 10:00:00'"
    )
    location: Optional[str] = Field(
        default=None,
        description="A human-readable location string. Example: 'Karachi, PK'"
    )
    description: Optional[str] = Field(
        default=None,
        description="Public facing narrative text about the event. Example: 'Final quality check completed at facility.'"
    )

    passport: DigitalProductPassport = Relationship(back_populates="events")


class DPPExtraDetail(TimestampMixin, SQLModel, table=True):
    """
    Represents Flexible Key-Value attributes for the Passport.
    Allows Brands to add marketing data or additional details not covered by 
    the strict schema (e.g., 'Designer Story', 'Care Tips').
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique ID for the detail."
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id",
        description="The owner of this data."
    )
    passport_id: uuid.UUID = Field(
        foreign_key="digitalproductpassport.id",
        description="The passport this detail belongs to."
    )

    key: str = Field(
        index=True,
        description="The label or header for this detail. Example: 'Care Instructions'"
    )
    value: str = Field(
        description="The content or body text. Example: 'Wash cold, hang dry.'"
    )
    is_public: bool = Field(
        default=True,
        description="Whether this detail is visible on the public page. Example: True"
    )
    display_order: int = Field(
        default=0,
        description="Numeric value to control the sorting order on the frontend. Example: 1"
    )

    tenant: Tenant = Relationship(back_populates="dpp_extra_details")
    passport: DigitalProductPassport = Relationship(
        back_populates="extra_details")
