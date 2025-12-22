from typing import Optional, List, Dict, Any
from datetime import datetime, date
import uuid
from sqlmodel import SQLModel, Field, Relationship, JSON
from enum import Enum

# ==========================================
# 1. ENUMS & CONSTANTS
# ==========================================


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


# ==========================================
# 2. BASE MIXIN
# ==========================================


class TimestampMixin(SQLModel):
    """
    Standard audit timestamps for every table.
    """
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow}
    )

# ==========================================
# 3. RBAC (ROLES & PERMISSIONS)
# ==========================================


class RolePermissionLink(TimestampMixin, SQLModel, table=True):
    """
    Pivot table: Roles <-> Permissions.
    """
    role_id: uuid.UUID = Field(foreign_key="role.id", primary_key=True)
    permission_id: uuid.UUID = Field(
        foreign_key="permission.id", primary_key=True)


class Permission(TimestampMixin, SQLModel, table=True):
    """
    Atomic actions (e.g., 'product:create', 'request:approve').
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    key: str = Field(unique=True, index=True)
    description: Optional[str] = None

    roles: List["Role"] = Relationship(
        back_populates="permissions", link_model=RolePermissionLink)


class Role(TimestampMixin, SQLModel, table=True):
    """
    Can be System Global (tenant_id=None) or Custom Tenant Role.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="tenant.id")

    name: str = Field(index=True)
    description: Optional[str] = None

    permissions: List["Permission"] = Relationship(
        back_populates="roles", link_model=RolePermissionLink)
    memberships: List["TenantMember"] = Relationship(back_populates="role")
    tenant: Optional["Tenant"] = Relationship(back_populates="custom_roles")

# ==========================================
# 4. IDENTITY & TENANCY
# ==========================================


class Tenant(TimestampMixin, SQLModel, table=True):
    """
    The Organization (Brand X or Manufacturer Y).
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(index=True)
    slug: str = Field(unique=True, index=True)
    type: TenantType = Field(default=TenantType.BRAND)
    status: TenantStatus = Field(default=TenantStatus.ACTIVE)

    # Relationships
    members: List["TenantMember"] = Relationship(back_populates="tenant")
    custom_roles: List["Role"] = Relationship(back_populates="tenant")
    invitations: List["TenantInvitation"] = Relationship(
        back_populates="tenant")

    # Ownership
    products: List["Product"] = Relationship(back_populates="tenant")
    suppliers: List["Supplier"] = Relationship(
        back_populates="tenant")  # Address Book
    custom_materials: List["Material"] = Relationship(back_populates="tenant")

    # Passport Extras
    dpp_extra_details: List["DPPExtraDetail"] = Relationship(
        back_populates="tenant")


class User(TimestampMixin, SQLModel, table=True):
    """
    Global User.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    first_name: str
    last_name: str
    is_active: bool = Field(default=True)

    memberships: List["TenantMember"] = Relationship(back_populates="user")


class TenantMember(TimestampMixin, SQLModel, table=True):
    """
    User <-> Tenant Link.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenant.id", index=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)

    role_id: uuid.UUID = Field(foreign_key="role.id")

    tenant: Tenant = Relationship(back_populates="members")

    status: MemberStatus = Field(default=MemberStatus.ACTIVE)

    user: User = Relationship(back_populates="memberships")
    role: Role = Relationship(back_populates="memberships")


class TenantInvitation(TimestampMixin, SQLModel, table=True):
    """
    Invite flow.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenant.id")
    email: str = Field(index=True)
    token: str = Field(unique=True)
    status: InvitationStatus = Field(default=InvitationStatus.PENDING)
    expires_at: datetime

    tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id", description="The target workspace.")
    role_id: uuid.UUID = Field(
        foreign_key="role.id", description="The role the user will receive upon acceptance.")

    # Actors
    inviter_id: uuid.UUID = Field(
        foreign_key="user.id", description="The existing member who sent the invite.")
    invitee_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="user.id", description="The receiver, if they already exist in the system.")

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
    The B2B Connection (Brand <-> Supplier).
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    brand_tenant_id: uuid.UUID = Field(foreign_key="tenant.id", index=True)
    supplier_tenant_id: Optional[uuid.UUID] = Field(
        foreign_key="tenant.id", default=None)
    supplier_email_invite: str
    status: ConnectionStatus = Field(default=ConnectionStatus.PENDING)

# ==========================================
# 5. SHARED LIBRARIES & RESOURCES
# ==========================================


class Material(TimestampMixin, SQLModel, table=True):
    """
    Reusable Material Definitions.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="tenant.id", description="Null for Global/System materials.")
    name: str = Field(index=True)
    code: str = Field(unique=True, index=True,
                      description="Unique standard code (e.g. ISO code or Internal ERP code).")
    material_type: MaterialType

    tenant: Optional[Tenant] = Relationship(back_populates="custom_materials")


class Certification(TimestampMixin, SQLModel, table=True):
    """
    Global Certs (GOTS, Oeko-Tex).
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(unique=True)
    issuer: str


class Supplier(TimestampMixin, SQLModel, table=True):
    """
    The 'Address Book' Entry.
    Owned by Brand, linked to 'connected_tenant_id' if they exist.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenant.id")  # The Brand
    connected_tenant_id: Optional[uuid.UUID] = Field(
        foreign_key="tenant.id", default=None)  # The Real Supplier

    name: str
    location_country: str

    tenant: Tenant = Relationship(back_populates="suppliers")
    facility_certs: List["SupplierFacilityCertification"] = Relationship(
        back_populates="supplier")


class SupplierFacilityCertification(TimestampMixin, SQLModel, table=True):
    """
    Factory-level certs (e.g. SA8000).
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    supplier_id: uuid.UUID = Field(foreign_key="supplier.id")
    name: str
    document_url: str
    valid_until: Optional[date] = None

    supplier: Supplier = Relationship(back_populates="facility_certs")

# ==========================================
# 6. PRODUCT ENGINE (ANCHOR & VERSION)
# ==========================================


class Product(TimestampMixin, SQLModel, table=True):
    """
    The Immutable Anchor.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenant.id", index=True)

    sku: str = Field(unique=True, index=True)
    gtin: Optional[str] = None

    tenant: Tenant = Relationship(back_populates="products")
    versions: List["ProductVersion"] = Relationship(back_populates="product")
    passport: Optional["DigitalProductPassport"] = Relationship(
        back_populates="product")
    spare_parts: List["SparePart"] = Relationship(back_populates="product")


class ProductVersion(TimestampMixin, SQLModel, table=True):
    """
    The Data Snapshot.
    Filled by PK Manufacturer, Approved by UK Brand.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    product_id: uuid.UUID = Field(foreign_key="product.id", index=True)

    # Workflow
    parent_version_id: Optional[uuid.UUID] = Field(
        foreign_key="productversion.id", default=None)
    version_number: int = Field(default=1)
    status: VersionStatus = Field(default=VersionStatus.WORKING_DRAFT)
    created_by_tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id")  # PK Manufacturer
    change_note: Optional[str] = None

    # --- ENVIRONMENT DATA (Per Single Piece) ---
    manufacturing_country: str = Field(default="PK")

    total_carbon_footprint_kg: Optional[float] = Field(
        description="CO2e for 1 unit")
    total_water_usage_liters: Optional[float] = Field(
        description="Water for 1 unit")
    total_energy_mj: Optional[float] = Field(description="Energy for 1 unit")

    # End of Life
    recycling_instructions: Optional[str] = Field(
        description="How to recycle.")
    recyclability_class: Optional[str] = Field(description="Class A-D")

    # Display Data
    product_name_display: str

    # Media
    media_gallery: List[Dict[str, Any]] = Field(
        default=[], sa_column=Field(sa_type=JSON))

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
    Material Breakdown & Sourcing.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    version_id: uuid.UUID = Field(foreign_key="productversion.id", index=True)

    # Definition
    material_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="material.id")
    unlisted_material_name: Optional[str] = None  # Fallback
    is_confidential: bool = False

    # Composition
    percentage: float

    # Sourcing & Impact
    origin_country: str = Field(description="Where material is coming from")
    material_carbon_footprint_kg: Optional[float] = Field(
        description="CO2 emission on procuring/producing material")
    transport_method: Optional[str] = Field(description="Sea/Air/Road")

    version: ProductVersion = Relationship(back_populates="materials")


class VersionSupplier(TimestampMixin, SQLModel, table=True):
    """
    Supply Chain Map (Tier 1, 2, 3).
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    version_id: uuid.UUID = Field(foreign_key="productversion.id", index=True)
    supplier_id: uuid.UUID = Field(foreign_key="supplier.id")
    role: SupplierRole

    version: ProductVersion = Relationship(back_populates="suppliers")


class VersionCertification(TimestampMixin, SQLModel, table=True):
    """
    Product-specific proofs (e.g. Transaction Certs).
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    version_id: uuid.UUID = Field(foreign_key="productversion.id", index=True)
    certification_id: Optional[uuid.UUID] = Field(
        foreign_key="certification.id")
    document_url: str
    valid_until: Optional[date] = None

    version: ProductVersion = Relationship(back_populates="certifications")


class SparePart(TimestampMixin, SQLModel, table=True):
    """
    Right-to-Repair Data.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    product_id: uuid.UUID = Field(foreign_key="product.id")
    name: str
    ordering_code: str

    product: Product = Relationship(back_populates="spare_parts")

# ==========================================
# 7. COLLABORATION (REQUESTS & COMMENTS)
# ==========================================


class DataContributionRequest(TimestampMixin, SQLModel, table=True):
    """
    The 'Job' assigned to the PK Manufacturer.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    connection_id: uuid.UUID = Field(foreign_key="tenantconnection.id")

    brand_tenant_id: uuid.UUID = Field(foreign_key="tenant.id")
    supplier_tenant_id: uuid.UUID = Field(foreign_key="tenant.id")

    # Version Tracking
    initial_version_id: uuid.UUID = Field(foreign_key="productversion.id")
    current_version_id: uuid.UUID = Field(foreign_key="productversion.id")

    status: RequestStatus = Field(default=RequestStatus.SENT)

    comments: List["CollaborationComment"] = Relationship(
        back_populates="request")


class CollaborationComment(TimestampMixin, SQLModel, table=True):
    """
    Chat & Rejection Feedback.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    request_id: uuid.UUID = Field(
        foreign_key="datacontributionrequest.id", index=True)

    author_user_id: uuid.UUID = Field(foreign_key="user.id")

    body: str = Field(description="The message content.")
    is_rejection_reason: bool = Field(
        default=False, description="Highlights comment if rejecting.")

    request: DataContributionRequest = Relationship(back_populates="comments")

# ==========================================
# 8. PASSPORT (OUTPUT)
# ==========================================


class DigitalProductPassport(TimestampMixin, SQLModel, table=True):
    """
    The Public Digital Twin.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenant.id", index=True)
    product_id: uuid.UUID = Field(foreign_key="product.id", unique=True)

    public_uid: str = Field(unique=True, index=True)
    status: DPPStatus = Field(default=DPPStatus.DRAFT)

    # Active Pointer
    active_version_id: Optional[uuid.UUID] = Field(
        foreign_key="productversion.id")

    # QR & Hosting
    qr_code_image_url: Optional[str] = None
    target_url: str = Field(description="The live link.")
    style_config: Dict[str, Any] = Field(
        default={}, sa_column=Field(sa_type=JSON))

    product: Product = Relationship(back_populates="passport")
    events: List["DPPEvent"] = Relationship(back_populates="passport")
    extra_details: List["DPPExtraDetail"] = Relationship(
        back_populates="passport", sa_relationship_kwargs={"cascade": "all, delete-orphan"})


class DPPEvent(SQLModel, table=True):
    """
    Immutable Journey Log.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    passport_id: uuid.UUID = Field(
        foreign_key="digitalproductpassport.id", index=True)
    event_type: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    location: Optional[str] = None
    description: Optional[str] = None

    passport: DigitalProductPassport = Relationship(back_populates="events")


class DPPExtraDetail(TimestampMixin, SQLModel, table=True):
    """
    Flexible Attributes (e.g. Marketing, Story).
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenant.id")
    passport_id: uuid.UUID = Field(foreign_key="digitalproductpassport.id")

    key: str = Field(index=True)
    value: str
    is_public: bool = True
    display_order: int = 0

    tenant: Tenant = Relationship(back_populates="dpp_extra_details")
    passport: DigitalProductPassport = Relationship(
        back_populates="extra_details")
