from typing import Optional, List, Dict, Any
from datetime import datetime, date
import uuid
from sqlmodel import SQLModel, Field, Relationship, JSON
from sqlalchemy import Column, Index, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from enum import Enum

# ENUMS

# ==============================================================================
# 1. TENANCY & ONBOARDING
# defines who is accessing the system and their operational state.
# ==============================================================================


class TenantType(str, Enum):
    """
    Categorizes the organization's role in the supply chain ecosystem.
    Determines feature availability (e.g., Suppliers see 'Requests', Brands see 'Analytics').
    """
    BRAND = "brand"               # The retailer or entity connecting with consumers.
    # Manufacturers, material providers, or assemblers.
    SUPPLIER = "supplier"
    # Internal platform staff with superuser privileges.
    SYSTEM_ADMIN = "system_admin"


class TenantStatus(str, Enum):
    """
    The operational lifecycle state of an Organization's account.
    """
    ACTIVE = "active"             # Fully operational account.
    # Temporarily blocked (e.g., payment issues or investigation).
    SUSPENDED = "suspended"
    # Soft-deleted. Data preserved but no login access.
    ARCHIVED = "archived"


class MemberStatus(str, Enum):
    """
    The operational status of a specific User's membership within a Tenant.
    Controls immediate access to that specific organization's data.
    """
    ACTIVE = "active"         # User has full granted access to the Tenant.
    # User is blocked from this Tenant (e.g., Security risk), but history is kept.
    SUSPENDED = "suspended"
    # User has left the organization or account was disabled by an admin.
    INACTIVE = "inactive"


class InvitationStatus(str, Enum):
    """
    Status of an outbound invite via TenantInvitation.
    """
    PENDING = "pending"       # Email sent, waiting for click.
    ACCEPTED = "accepted"     # User clicked link and joined.
    EXPIRED = "expired"       # Token is no longer valid.
    REVOKED = "revoked"       # Admin cancelled the invite before it was used.


class ConnectionStatus(str, Enum):
    """
    Status of the B2B Handshake (TenantConnection).
    """
    PENDING = "pending"       # Request sent to Supplier, no response yet.
    ACTIVE = "active"         # Connection established, data flows freely.
    REJECTED = "rejected"     # Supplier declined the connection.
    SUSPENDED = "suspended"   # Connection paused (e.g., Contract ended).


# ==============================================================================
# 2. COLLABORATION & WORKFLOW
# Defines how Brands and Suppliers interact to generate data.
# ==============================================================================

class RequestStatus(str, Enum):
    """
    The state of a 'DataContributionRequest' (Work Order) sent from Brand to Supplier.
    """
    SENT = "sent"                        # Email dispatched, waiting for Supplier to open.
    ACCEPTED = "accepted"                # Supplier acknowledged the request.
    # Supplier refused (e.g., "We don't make this anymore").
    DECLINED = "declined"
    # Supplier is actively filling out the forms.
    IN_PROGRESS = "in_progress"
    # Supplier locked the data and sent it back.
    SUBMITTED = "submitted"
    # Brand reviewed and found errors; returned to Supplier.
    CHANGES_REQUESTED = "changes_req"
    COMPLETED = "completed"              # Brand finally approved the data.


# ==============================================================================
# 3. PRODUCT & SUPPLY CHAIN DATA
# Defines the input side: The Product Identity and Technical Versions.
# ==============================================================================

class ProductLifecycleStatus(str, Enum):
    """
    Business status of the Product Identity (Shell) itself. 
    Distinguishes between products currently being made vs. old references.
    """
    ACTIVE = "active"             # Currently being manufactured and sold.
    # No longer made, but Passports remain active for historical lookup.
    DISCONTINUED = "discontinued"
    # Brand no longer supports inquiries; potentially legacy.
    END_OF_SUPPORT = "eos"
    # Internal setup/placeholder before official launch.
    PRE_RELEASE = "pre_release"


class ProductVersionStatus(str, Enum):
    """
    Status of the Technical Data Snapshot (Owned by Supplier).
    This strictly controls the immutability logic of the 'ProductVersion'.
    """
    DRAFT = "draft"           # Supplier is editing. Mutable. Not visible to Brand.
    SUBMITTED = "submitted"   # Locked/Frozen. Visible to Brand for QA review.
    # Brand accepted the data. Ready to link to a Passport.
    APPROVED = "approved"
    # Brand requested changes. System must clone this to a new draft.
    REJECTED = "rejected"


class VisibilityScope(str, Enum):
    """
    Field-level permission mask.
    Determines who can see specific data points (e.g., Supplier Identity).
    """
    PUBLIC = "public"            # Visible on the open Consumer DPP.
    RESTRICTED_AUDIT = "audit"   # Visible only to Token-Gated Auditors.
    RESTRICTED_RECYCLE = "recycle"  # Visible only to professional recyclers.
    # Never exposed; for Brand/Supplier analytics only.
    INTERNAL = "internal"


class MaterialType(str, Enum):
    SYNTHETIC = "synthetic"
    NATURAL = "natural"
    BLEND = "blend"
    RECYCLED = "recycled"
    METAL = "metal"
    OTHER = "other"


class CertificateCategory(str, Enum):
    """
    Classifies legal certificates for standardized audit reporting.
    """
    ENVIRONMENTAL = "environmental"      # e.g., ISO 14001, Carbon Trust.
    # e.g., SA8000, Fair Trade, Labor standards.
    SOCIAL = "social"
    # e.g., Oeko-Tex, REACH, Restricted substances.
    CHEMICAL_SAFETY = "chemical_safety"
    # e.g., Certificate of Origin, Made In Green.
    ORIGIN = "origin"
    # e.g., Anti-Bribery, Corporate Bylaws.
    GOVERNANCE = "governance"
    QUALITY = "quality"                  # e.g., ISO 9001.
    OTHER = "other"                      # Miscellaneous docs.


# ==============================================================================
# 4. ASSETS & EVIDENCE
# Defines the file types used for Proof (Technical) vs Marketing (Visual).
# ==============================================================================

class ArtifactType(str, Enum):
    """
    Classifies 'Strict' files used for compliance and legal evidence.
    Usually immutable WORM storage.
    """
    IMAGE = "image"                 # Photographic proof.
    VIDEO = "video"                 # Video evidence/audit.
    DOCUMENT = "document"           # PDFs, Manuals.
    CERTIFICATE = "certificate"     # Official compliance PDF.
    AUDIT_REPORT = "audit_report"   # Third-party testing results.
    OTHER = "other"                 # Unclassified files.


class MediaType(str, Enum):
    """
    Classifies 'Marketing' assets used for the visual header of the Passport.
    Optimized for CDN delivery.
    """
    IMAGE = "image"        # Product photography.
    VIDEO = "video"        # Promotional video.
    DOCUMENT = "document"  # User Manuals/Care Guides (PDF).
    MODEL_3D = "model_3d"  # GLB/USDZ files for Augmented Reality.


# ==============================================================================
# 5. PASSPORT PUBLICATION (DPP)
# Defines the Public-Facing entity, QR Codes, and Access Control.
# ==============================================================================

class DPPLifecycleStatus(str, Enum):
    """
    The operational state of the Passport container (QR Code) itself.
    This controls the High-Level Routing (What happens when scanned?).
    """
    ACTIVE = "active"             # Normal: Resolves to the 'published' data version.
    # QR Code exists, but scans show "Coming Soon".
    DRAFT_CONTAINER = "draft"
    # Disabled (Payment/Compliance issue). Shows "Unavailable".
    SUSPENDED = "suspended"
    # EMERGENCY: Redirects immediately to Safety Warning page.
    RECALLED = "recalled"
    # EoL: Shows static "Product History" but no new updates.
    DECOMMISSIONED = "decommissioned"


class DPPVersionStatus(str, Enum):
    """
    The status of a specific Content Snapshot within the Passport.
    """
    DRAFT = "draft"           # Brand is assembling the template/content.
    PUBLISHED = "published"   # This is the version consumers currently see.
    # Old version, preserved for historical legal protection.
    ARCHIVED = "archived"


class DPPAccessType(str, Enum):
    """
    The General Security Level required to view the Passport.
    """
    PUBLIC = "public"             # Frictionless access (Standard consumer goods).
    # Shared PIN required (B2B / Limited drop).
    PASSWORD_PROTECTED = "password"
    # Requires Bearer Token (Regulators/Auditors).
    TOKEN_GATED = "token_gated"
    GEO_RESTRICTED = "geo_restricted"  # Dynamic access based on User IP.


class AccessRuleType(str, Enum):
    """
    The Specific Logic for granular Access Rules (e.g., Geo-Fencing).
    """
    GEO_ALLOW = "geo_allow"       # Whitelist: Only users in these Countries.
    GEO_BLOCK = "geo_block"       # Blacklist: Block users in these Countries.
    PASSWORD = "password"         # Logic: Validate against stored hash.
    # Logic: Only valid between Start_Date and End_Date.
    TIME_WINDOW = "time_window"
    # Logic: Allow specific Corporate/Gov IP Ranges.
    IP_WHITELIST = "ip_whitelist"


# ==============================================================================
# 6. TEMPLATING & LOCALIZATION (UI)
# Defines how the data is rendered and translated.
# ==============================================================================

class TemplateCategory(str, Enum):
    """
    Organizational tags for the DPP Design Template Library.
    """
    GENERIC = "generic"           # Universal default layout.
    APPAREL = "apparel"           # Clothing-specific (focus on materials).
    FOOTWEAR = "footwear"         # Shoe-specific layouts.
    ELECTRONICS = "electronics"   # Tech-specs heavy layouts.
    LUXURY = "luxury"             # Visual-heavy, minimalistic data.
    MINIMALIST = "minimalist"     # Clean, simple data.
    DATA_HEAVY = "data_heavy"     # Spreadsheet/Table dense (for B2B).


class TemplateFieldType(str, Enum):
    """
    Classifies UI variables to guide the Translation System.
    Ensures context isn't lost during localization.
    """
    TEXT = "text"           # Simple strings (e.g., "Description").
    RICH_TEXT = "rich_text"  # Strings supporting Markdown/HTML.
    HEADER = "header"       # Short headlines (Capitalization rules may apply).
    LABEL = "label"         # Tiny form labels (space constrained).
    # Values needing locale formatting (e.g., 1.000 vs 1,000).
    NUMBER = "number"
    COLOR = "color"         # Values that must NOT be translated (Hex Codes).


# ==============================================================================
# 7. CIRCULARITY & RECYCLING
# Defines End-of-Life actions and disassembly guides.
# ==============================================================================

class RecyclingAction(str, Enum):
    """
    The Primary Call-to-Action (CTA) for the Consumer at product EoL.
    """
    RECYCLE = "recycle"           # Standard material recovery.
    REUSE = "reuse"               # Donation, thrift, or second-hand use.
    COMPOST = "compost"           # Industrial or home compostable.
    RETURN_TO_BRAND = "return_to_brand"  # Brand Take-back scheme.
    SPECIAL_HANDLING = "special_handling"  # Hazardous/Electronics (WEEE).
    LANDFILL = "landfill"         # No viable recovery option.


class StageContentType(str, Enum):
    """
    Structural type for content blocks within a Disassembly Guide.
    Determines the Frontend Widget component.
    """
    TEXT_BLOCK = "text_block"       # Markdown paragraph.
    IMAGE = "image"                 # Photo of the step.
    VIDEO = "video"                 # Clip of the specific action.
    DOCUMENT = "document"           # Detailed PDF schematic.
    WARNING_BLOCK = "warning_block"  # Highlighted Alert Box (Safety critical).


# ==============================================================================
# 8. SYSTEM & AUDITING
# Defines low-level maintenance logs.
# ==============================================================================

class AuditAction(str, Enum):
    """
    The specific activity performed on a database entity.
    Used for the immutable Ledger.
    """
    CREATE = "create"             # New record insertion.
    UPDATE = "update"             # modification of fields.
    DELETE = "delete"             # Physical database removal (Rare).
    SOFT_DELETE = "soft_delete"   # Logical removal (flag toggle).
    PUBLISH = "publish"           # Changing state to Public.
    LOGIN = "login"               # User authentication event.
    DOWNLOAD = "download"         # File access (e.g., Evidence download).


# CORE MODELS

# ==============================================================================
# 1. BASE MIXINS (INFRASTRUCTURE)
# ==============================================================================

class TimestampMixin(SQLModel):
    """
    A foundational mixin that provides standard audit timestamps for database records.
    This ensures that every entity inheriting from this mixin tracks when it was
    originally created and when it was last modified, which is crucial for data
    integrity and history tracking. We use this to sort versions and track activity.
    """
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="The exact UTC timestamp when this record was first persisted in the database. This value is immutable once set and represents the birth of the record."
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
        description="The exact UTC timestamp when this record was last modified. It updates automatically on every save, providing a trail of the last interaction."
    )


class SoftDeleteMixin(SQLModel):
    """
    Provides logical deletion capabilities instead of physical row removal.
    Crucial for audit logs: we never truly destroy data, we only hide it.
    """
    is_deleted: bool = Field(
        default=False,
        index=True,
        description="Flag indicating if the record is logically deleted. If True, it should be filtered out of standard queries."
    )
    deleted_at: Optional[datetime] = Field(
        default=None,
        description="The UTC timestamp when the record was marked as deleted. Used for audit history to know exactly when the asset was removed."
    )


# ==============================================================================
# 2. AUTHORIZATION (RBAC)
# ==============================================================================


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


# ==============================================================================
# 3. IDENTITY & TENANCY
# ==============================================================================

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
    custom_roles: List["Role"] = Relationship(
        back_populates="tenant")
    members: List["TenantMember"] = Relationship(
        back_populates="tenant")
    invitations: List["TenantInvitation"] = Relationship(
        back_populates="tenant")
    supplier_profiles: List["SupplierProfile"] = Relationship(
        back_populates="tenant",
        sa_relationship_kwargs={"foreign_keys": "[SupplierProfile.tenant_id]"}
    )
    supplier_artifacts: List["SupplierArtifact"] = Relationship(
        back_populates="tenant")
    material_definitions: List["MaterialDefinition"] = Relationship(
        back_populates="tenant")
    certificate_types: List["CertificateDefinition"] = Relationship(
        back_populates="tenant")
    products: List["Product"] = Relationship(back_populates="tenant")
    passports: List["DPP"] = Relationship(back_populates="tenant")
    dpp_templates: List["DPPTemplate"] = Relationship(back_populates="tenant")


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


# ==============================================================================
# 4. B2B NETWORK & SUPPLY CHAIN LOGIC
# ==============================================================================

class SupplierProfile(TimestampMixin, SQLModel, table=True):
    """
    Represents an entry in a Brand's 'Address Book' (Shadow Profile).
    This allows Brands to list suppliers and attach private notes/docs 
    before the Supplier is fully onboarded.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    # The Owner (The Brand)
    tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id",
        index=True,
        description="The Brand that owns this specific address book entry."
    )

    # The Link (The Real Supplier)
    connected_tenant_id: Optional[uuid.UUID] = Field(
        foreign_key="tenant.id",
        default=None,
        index=True,
        description="DENORMALIZED: If linked, this points to the real Supplier Tenant. Source of truth is TenantConnection."
    )

    # Profile Data (Managed by Brand)
    name: str = Field(
        description="The Brand's internal alias for this supplier.")
    description: Optional[str] = Field(default=None)
    location_country: str = Field(
        index=True,
        description="ISO 2-letter country code. Critical for Geo-Fencing calculations on 'Blind' supply chains."
    )

    # Contact Info (Address Book features)
    contact_email: Optional[str] = Field(
        default=None, description="Saved contact email.")
    contact_name: Optional[str] = Field(
        default=None, description="Saved point of contact (e.g., 'Mr. Smith').")

    # Internal Meta
    is_favorite: bool = Field(default=False, description="For UI sorting.")

    # Relationships
    tenant: "Tenant" = Relationship(
        back_populates="supplier_profiles",
        sa_relationship_kwargs={"foreign_keys": "SupplierProfile.tenant_id"}
    )

    # The Real Supplier Tenant Object (Useful for code access)
    connected_tenant: Optional["Tenant"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "SupplierProfile.connected_tenant_id"}
    )

    # 1:1 Connection State
    connection: Optional["TenantConnection"] = Relationship(
        back_populates="supplier_profile",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan", "uselist": False}
    )


class TenantConnection(TimestampMixin, SQLModel, table=True):
    """The active link between Brand and Supplier."""
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

    invitation_token: Optional[str] = Field(
        default=None,
        index=True,
        unique=True,
        description="Secure token included in the email link to identify this connection request during registration."
    )

    retry_count: int = Field(
        default=0,
        description="Tracks how many times the invite has been resent. Limit is usually 3."
    )

    request_note: Optional[str] = Field(
        default=None,
        description="A note from the Brand explaining the invite or re-invite."
    )

    status: ConnectionStatus = Field(default=ConnectionStatus.PENDING)

    supplier_profile: "SupplierProfile" = Relationship(
        back_populates="connection")


# ==============================================================================
# 5. LIBRARIES & MASTER DATA
# ==============================================================================

class CertificateDefinition(TimestampMixin, SQLModel, table=True):
    """
    Represents the authoritative definition or 'Class' of a standard/regulation.
    This model serves as the library of available certifications in the system.
    It supports a hybrid ownership model: System Admins can seed global standards (like GOTS, ISO),
    while Suppliers can define their own internal standards (like 'Internal Lab Report') by setting the tenant_id.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="The unique identifier for this certificate standard definition."
    )

    tenant_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="tenant.id",
        description="The owner of this definition. If NULL, it is a System/Global Standard available to all users. If set, it is a Custom Standard private to that Supplier."
    )

    name: str = Field(
        index=True,
        description="The official legal name of the standard or certification. Example: 'Global Organic Textile Standard (GOTS) v7.0'."
    )

    issuer_authority: str = Field(
        description="The governing body or organization that officially owns and manages this standard. Example: 'Global Standard gGmbH' or 'ISO'."
    )

    category: CertificateCategory = Field(
        description="The high-level legal classification of this standard (e.g., Environmental, Social). This is used for grouping in audit reports and consumer views."
    )

    description: Optional[str] = Field(
        default=None,
        description="A summary of what compliance with this standard entails. Example: 'Certifies organic status of textiles from harvesting to labeling.'"
    )

    # Relationships
    tenant: Optional["Tenant"] = Relationship(
        back_populates="certificate_types")

    # Traceability: We can track how many product batches claimed compliance with this standard
    linked_version_certificates: List["ProductVersionCertificate"] = Relationship(
        back_populates="certificate_type")


class MaterialDefinition(TimestampMixin, SQLModel, table=True):
    """
    A reusable material profile defined strictly by the Supplier or the System.
    Brands do not have access to create these. This allows the supplier to manage
    their internal inventory of materials (e.g., 'Internal Recycled Poly Batch A').
    When linked to a product, data is snapshotted, not referenced.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="tenant.id",
        description="The Supplier Tenant ID. If None, it is a System/Global Standard Material."
    )

    name: str = Field(description="The common name of the material.")
    code: str = Field(description="Internal ERP code or standard ISO code.")
    description: Optional[str] = Field(
        default=None, description="Details about composition.")
    material_type: MaterialType = Field(
        default=MaterialType.OTHER, description="Category.")
    default_carbon_footprint: Optional[float] = Field(
        description="Baseline CO2e per kg for this material.")

    tenant: Optional[Tenant] = Relationship(
        back_populates="material_definitions")


class SupplierArtifact(TimestampMixin, SQLModel, table=True):
    """
    Represents the Supplier's private vault of files (Images, PDFs, Videos).
    This acts as a library. When a supplier wants to "add" a document to a product,
    they select from here, and the system creates a copy (snapshot) in the ProductArtifact table.
    The Supplier maintains ownership of this original record.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique identifier for the artifact in the supplier's vault."
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id",
        description="The Supplier Tenant who owns this file. Brands cannot see this vault directly."
    )

    file_name: str = Field(
        description="The internal filename or label for the file.")
    display_name: Optional[str] = Field(default=None)
    file_url: str = Field(
        description="The secure S3/Storage URL where the file is physically located.")
    file_type: ArtifactType = Field(
        description="Categorization of the file (e.g., Image, Certificate).")

    description: Optional[str] = Field(
        default=None,
        description="Internal notes about what this file contains or its expiration."
    )

    tenant: Tenant = Relationship(back_populates="supplier_artifacts")


# ==============================================================================
# 6. PRODUCT SHELL (BRAND IDENTITY)
# ==============================================================================

class Product(TimestampMixin, SQLModel, table=True):
    """
    The immutable anchor owned by the Brand.
    This contains only the high-level identity (SKU, Name) and the Brand's
    Marketing Media. It does NOT contain supply chain data.
    The Brand creates this shell and then requests the Supplier to fill the 'Version'.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="The persistent unique identifier for the product entity."
    )
    tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id",
        description="The Brand Tenant that owns this product identity."
    )

    sku: str = Field(unique=True, index=True,
                     description="Stock Keeping Unit.")

    ean: Optional[str] = Field(
        index=True, description="European Article Number")
    upc: Optional[str] = Field(
        index=True, description="Universal Product Code")
    internal_erp_id: Optional[str] = Field(
        index=True, description="ID in Brand's SAP/Oracle system")

    name: str = Field(description="The marketing name of the product.")

    description: Optional[str] = Field(
        description="The description of the product.")

    lifecycle_status: ProductLifecycleStatus = Field(
        default=ProductLifecycleStatus.ACTIVE,
        index=True,
        description="Current business status (e.g., Active vs Discontinued). Allows filtering out old products from 'New Shipment' dropdowns without deleting the historical record."
    )

    main_image_url: Optional[str] = Field(
        default=None,
        description="DENORMALIZED: The cached URL of the 'is_main=True' media asset. Enables high-performance rendering of Product Grids without performing SQL Joins on the ProductMedia table."
    )

    pending_version_name: Optional[str] = Field(
        default=None,
        description="Stores the version name (e.g. 'Spring Launch') provided by Brand at creation. "
                    "Used to name the first ProductVersion when a Supplier is finally assigned."
    )

    tenant: Tenant = Relationship(back_populates="products")
    marketing_media: List["ProductMedia"] = Relationship(
        back_populates="product")

    # One-to-Many: A product has many technical versions submitted by suppliers
    technical_versions: List["ProductVersion"] = Relationship(
        back_populates="product")

    # Keep this one! This is the correct link.
    passport: Optional["DPP"] = Relationship(back_populates="product")


class ProductMedia(TimestampMixin, SoftDeleteMixin, SQLModel, table=True):
    """
    Represents the Marketing and E-Commerce visual assets owned by the Brand.
    These are linked to the high-level Product ID and are used for the DPP header/gallery.
    Unlike technical data, these can be updated (via soft-delete and re-upload) to keep marketing fresh.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique identifier for this media asset."
    )
    product_id: uuid.UUID = Field(
        foreign_key="product.id",
        index=True,
        description="The parent Product this media belongs to."
    )

    # ==========================
    # FILE METADATA (Consistent)
    # ==========================
    file_url: str = Field(
        description="The secure, hosted URL of the high-resolution file. Example: 'https://cdn.brand.com/products/shoe_v1.jpg'"
    )

    file_name: str = Field(
        description="The original filename uploaded by the user. Useful for internal management. Example: 'Summer_Campaign_Shoot_05.jpg'"
    )

    display_name: Optional[str] = Field(default=None)

    file_type: MediaType = Field(
        description="The classification of the file (Image, Video, etc.). Used by the frontend to determine which player/viewer to render."
    )

    description: Optional[str] = Field(
        default=None,
        description="Public-facing Alt Text or Caption for the media. Crucial for Accessibility (a11y) and SEO on the DPP page."
    )

    # ==========================
    # DISPLAY LOGIC
    # ==========================
    is_main: bool = Field(
        default=False,
        description="Flag indicating if this is the 'Hero' image to be displayed on the product card or main header. Only one active media per product should have this True."
    )

    display_order: int = Field(
        default=0,
        description="Numeric value to control the sorting order in the gallery. Lower numbers appear first."
    )

    # Soft Delete fields (is_deleted, deleted_at) are inherited from SoftDeleteMixin

    product: "Product" = Relationship(back_populates="marketing_media")


# ==============================================================================
# 7. TECHNICAL DATA & SNAPSHOTS (SUPPLIER SUBMISSION)
# ==============================================================================

class ProductVersion(TimestampMixin, SQLModel, table=True):
    """
    The technical data container owned by the Supplier.

    CRITICAL CONSISTENCY LOGIC:
    1. STATE MACHINE: 
       - While status is 'DRAFT' or 'REVISION_REQ', the Supplier may edit fields directly.
       - Once status becomes 'SUBMITTED', 'APPROVED', or 'PUBLISHED', this record is LOCKED (Read-Only).

    2. NO EDIT ON SUBMIT:
       - If a Brand requests changes to a 'SUBMITTED' version, the System MUST NOT edit this row.
       - The System must create a NEW ProductVersion (Clone) with status 'DRAFT', 
         incrementing an internal revision counter if necessary.
       - The old version status changes to 'ARCHIVED' or 'REPLACED'.

    3. SINGLE SOURCE OF TRUTH:
       - The DPP Generation Engine will only ever look at the version marked 'APPROVED' 
         for the specific SKU batch.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique ID for this technical snapshot."
    )
    product_id: uuid.UUID = Field(
        foreign_key="product.id",
        description="The parent product shell."
    )
    supplier_tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id",
        description="The Supplier who owns this specific data entry."
    )

    version_sequence: int = Field(
        default=0,
        index=True,
        description="A monotonically increasing integer strictly for this Product ID. "
                    "Drafts may start at 0. When 'Submitted' or 'Approved', system must set this to MAX(current_versions) + 1. "
                    "Used to deterministically order 'v1', 'v2', 'v3' in UI lists."
    )

    version_name: str = Field(
        description="Label for this batch (e.g., 'Lot 405').")

    change_summary: Optional[str] = Field(
        default=None,
        description="The 'Commit Message' for this version. Mandatory if this is a clone/revision of a previous rejected version. Example: 'Corrected Polyester % per brand audit.'"
    )

    status: ProductVersionStatus = Field(
        default=ProductVersionStatus.DRAFT,
        description="The lifecycle of this data submission (Draft -> Submitted -> Approved)."
    )

    # Core Environmental Data
    manufacturing_country: Optional[str] = Field(
        default=None, description="Where final assembly happened.")

    mass_kg: float = Field(
        default=0.0,
        description="The net weight of the product in Kilograms. Critical consistency field: Total Carbon Footprint is often derived from (Material Emission Factors * Mass). If Mass changes, Carbon must be recalculated."
    )

    total_carbon_footprint: float = Field(
        default=0.0, description="Aggregated CO2e.")

    product: Product = Relationship(back_populates="technical_versions")

    # Children (The Detailed Snapshots)
    materials: List["ProductVersionMaterial"] = Relationship(
        back_populates="version")
    certificates: List["ProductVersionCertificate"] = Relationship(
        back_populates="version")
    supply_chain: List["ProductVersionSupplyNode"] = Relationship(
        back_populates="version")
    recycling_info: Optional["ProductVersionRecycling"] = Relationship(
        back_populates="version")

    # Supplier's Evidence (Docs linked from their Artifact Vault)
    artifacts: List["ProductVersionArtifact"] = Relationship(
        back_populates="version")


class ProductVersionCertificate(TimestampMixin, SQLModel, table=True):
    """
    The 'Evidence Snapshot' linking a specific Product Batch (Version) to a Certificate Type.

    CRITICAL AUDIT LOGIC:
    This table acts as a self-contained archive. It copies BOTH the metadata (dates, issuer)
    AND the file details (URL, name) from the source.

    If the Supplier deletes the original 'SupplierArtifact' from their library,
    this record REMAINS VALID because it holds its own copy of the file URL and details.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique ID for this specific compliance record."
    )

    # 1. The Subject (The Product Batch)
    version_id: uuid.UUID = Field(
        foreign_key="productversion.id",
        index=True,
        description="The specific product batch/version this certificate is validating."
    )

    # 2. The Definition (The Standard)
    certificate_type_id: uuid.UUID = Field(
        foreign_key="certificatedefinition.id",
        description="Link to the standard definition (e.g., GOTS) for categorization."
    )

    # 3. The Lineage (Traceability)
    # We keep this OPTIONAL. If the supplier deletes the original, this becomes None,
    # but the snapshot fields below ensure the legal proof is not lost.
    source_artifact_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="supplierartifact.id",
        description="Link to the original library record. Used only to track which folder/file the supplier selected. If the supplier deletes the original, this link breaks, but the data below persists."
    )

    # =========================================================
    # SNAPSHOT: ARTIFACT FILE DATA (The Immutable Proof)
    # =========================================================
    file_url: str = Field(
        description="The direct, permanent URL to the document proof. Even if the source artifact is deleted, this URL must remain accessible for auditors."
    )

    file_name: str = Field(
        description="The filename at the time of attachment. Example: 'GOTS_Report_2024_Signed.pdf'."
    )

    file_type: str = Field(
        description="The MIME type or extension of the file. Example: 'application/pdf'."
    )

    file_display_name: Optional[str] = Field(default=None)

    # =========================================================
    # SNAPSHOT: CERTIFICATE METADATA (The Legal Details)
    # =========================================================
    snapshot_name: str = Field(
        description="The display name of the certificate. Example: 'GOTS Transaction Certificate'."
    )

    snapshot_issuer: str = Field(
        description="The specific auditing body that signed this document. Example: 'Control Union Certifications'."
    )

    issuer_address: Optional[str] = Field(
        default=None,
        description="City/Address of the auditing office. Useful for detecting fraud (e.g., A factory in China certified by an office in Brazil requires extra scrutiny)."
    )
    issuer_country: Optional[str] = Field(
        default=None,
        description="ISO 2-letter country code of the issuer. Example: 'DE'."
    )

    reference_number: Optional[str] = Field(
        default=None,
        description="The unique Transaction Certificate (TC) number. Crucial for legal verification. Example: 'TC-2023-999-XYZ'."
    )

    valid_from: Optional[date] = Field(
        default=None,
        description="The start date of validity."
    )

    valid_until: Optional[date] = Field(
        default=None,
        description="The expiration date. Used for compliance flags."
    )

    was_valid_at_submission: bool = Field(default=True)
    compliance_check_timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="The exact moment the system calculated 'was_valid_at_submission'. Audit proof that the check was performed programmatically at that specific time."
    )

    file_hash_sha256: Optional[str] = Field(
        description="Cryptographic hash of the file content for audit verification.")

    # Relationships
    version: "ProductVersion" = Relationship(back_populates="certificates")

    certificate_type: "CertificateDefinition" = Relationship(
        back_populates="linked_version_certificates"
    )

    # We rename this to 'source_artifact' to imply it is just the origin, not the current truth.
    source_artifact: Optional["SupplierArtifact"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "ProductVersionCertificate.source_artifact_id"}
    )


class ProductVersionArtifact(TimestampMixin, SoftDeleteMixin, SQLModel, table=True):
    """
    A specific document attached to a Product Version.

    CRITICAL IMPLEMENTATION LOGIC:
    1. IMMUTABILITY: This record represents a LEGAL EVIDENCE SNAPSHOT. 
       Once the parent ProductVersion is 'APPROVED', this record must NEVER change.

    2. STORAGE STRATEGY (The "Deleted File" Paradox):
       - This model contains 'file_url'. This URL must point to a permanent storage location.
       - If the Supplier deletes the original 'SupplierArtifact', the file in S3/Blob Storage 
         linked here MUST NOT BE DELETED. 
       - Ideally, when creating this record, the backend should perform a 'Server-Side Copy' 
         of the file to a separate 'locked-evidence' bucket to ensure total isolation 
         from the Supplier's mutable library.

    3. INTEGRITY CHECK:
       - 'file_hash_sha256' is mandatory. It proves that the file content today matches 
         the file content at the moment of submission.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    version_id: uuid.UUID = Field(foreign_key="productversion.id", index=True)

    # Lineage (Informational only)
    source_artifact_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="supplierartifact.id",
        description="Reference to the original file in the Supplier's Library. If the Supplier deletes the original, this link is allowed to break (become None), but the data below must persist."
    )

    # Snapshot Metadata
    display_name: str = Field(description="Label (e.g., 'User Manual').")
    file_name: str = Field(
        description="Original filename (e.g., 'manual.pdf').")

    file_url: str = Field(
        description="PERMANENT URL. If using S3, this object must have Deletion Protection enabled."
    )

    file_hash_sha256: str = Field(
        index=True,
        description="Cryptographic hash of the file content. Validates that the file at 'file_url' has not been tampered with since upload."
    )

    file_type: ArtifactType = Field(
        description="Classification (Image, Document, Certificate) matching the SupplierArtifact model."
    )

    file_size_bytes: Optional[int] = Field(
        default=None,
        description="The exact size of the file in bytes. Used for: 1. Calculating download costs/time. 2. Additional security check (Collision Resistance) - checks must match both Hash AND Size."
    )

    description: Optional[str] = Field(
        default=None,
        description="Contextual notes specific to this attachment. Example: 'Uploaded at brand request for compliance.'"
    )

    version: "ProductVersion" = Relationship(back_populates="artifacts")
    source_artifact: Optional["SupplierArtifact"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "ProductVersionArtifact.source_artifact_id"}
    )


class ProductVersionMaterial(TimestampMixin, SQLModel, table=True):
    """
    A frozen record of a material used in a specific ProductVersion.
    This copies data from the 'MaterialDefinition' at the moment of creation.
    Even if the original definition changes, this record remains historically accurate.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    version_id: uuid.UUID = Field(foreign_key="productversion.id")

    # Provenance
    source_material_definition_id: Optional[uuid.UUID] = Field(
        description="Reference to the original library item (for lineage), if it exists."
    )

    # Snapshot Data (Stored as text/float, not lookups)
    material_name: str = Field(
        description="Name of the material at time of use.")
    percentage: float = Field(description="Composition percentage.")
    origin_country: str = Field(
        description="Where the raw material came from.")

    # Visibility
    visibility: VisibilityScope = Field(
        default=VisibilityScope.PUBLIC,
        description="Who is allowed to see this specific component (e.g. Restricted to Auditors)."
    )

    batch_number: Optional[str] = Field(
        description="The specific lot/batch number of the raw material used.")

    version: ProductVersion = Relationship(back_populates="materials")


class ProductVersionSupplyNode(TimestampMixin, SQLModel, table=True):
    """
    A frozen record of a supply chain actor for a specific ProductVersion.
    This stores the actual text data (Company Name, Country) as it was entered
    by the Supplier. It does not strictly link to a 'Tenant' to allow for
    unlisted/offline suppliers (The 'Blind' supply chain requirement).
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    version_id: uuid.UUID = Field(foreign_key="productversion.id")

    role: str = Field(description="Function (e.g. 'Spinner', 'Dyer').")
    company_name: str = Field(
        description="Name of the company performing the role.")
    location_country: str = Field(description="ISO country code.")

    version: ProductVersion = Relationship(back_populates="supply_chain")


# ==============================================================================
# 8. CIRCULARITY & END-OF-LIFE
# ==============================================================================

class ProductVersionRecycling(TimestampMixin, SoftDeleteMixin, SQLModel, table=True):
    """
    The top-level container for end-of-life (EoL) and recycling data attached to a ProductVersion.

    This model acts as the 'Header' for the recycling module, containing aggregated scores,
    legal classifications, and high-level safety warnings. It serves as the parent entity
    for the specific step-by-step 'ProductVersionRecyclingStages'.

    It is crucial for the Circular Economy calculations, allowing the system to display
    standardized scores (like Recyclability %) on the Digital Product Passport.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="The unique identifier for this recycling data block."
    )
    version_id: uuid.UUID = Field(
        foreign_key="productversion.id",
        unique=True,  # One info block per product version
        description="The Product Version (Batch) this information belongs to. Links the EoL data to the specific material composition of this batch."
    )

    # ==========================
    # SCORES & METRICS
    # ==========================
    total_recyclability_percentage: float = Field(
        default=0.0,
        description="The calculated percentage of the product's total mass that can be effectively recycled. Example: '95.5' implies 95.5% of the material can be recovered."
    )

    recycling_index_score: Optional[float] = Field(
        default=None,
        description="A normalized aggregate score (0.0 to 10.0) representing the ease of recycling based on industry standards (e.g., Circulytics). A higher score indicates better circularity performance."
    )

    # ==========================
    # CLASSIFICATION & LEGAL
    # ==========================
    recyclability_class: str = Field(
        description="A standard classification code indicating the ease of recycling or quality of recovered material. Example: 'Class A' or 'Gold Standard'."
    )

    waste_code: Optional[str] = Field(
        default=None,
        description="The official Waste Stream code based on local or international regulations (e.g., European Waste Catalogue EWC code). Crucial for professional recyclers to identify handling procedures. Example: '20 01 10' (Clothes)."
    )

    primary_action: RecyclingAction = Field(
        default=RecyclingAction.RECYCLE,
        description="The single most important action the consumer should take. Used to render the primary 'Call to Action' button on the DPP. Example: 'return_to_brand'."
    )

    is_hazardous: bool = Field(
        default=False,
        description="Flag indicating if the product contains materials defined as hazardous (e.g., Lithium, Mercury). If True, specific warning UI elements will be triggered."
    )

    # ==========================
    # PROCESS CONTEXT
    # ==========================
    collection_method: str = Field(
        default="Standard Collection",
        description="Instructions on how the item enters the recycling stream. Example: 'Kerbside Bin', 'Specialized E-Waste Drop-off', or 'In-Store Return'."
    )

    estimated_disassembly_time_minutes: Optional[int] = Field(
        default=None,
        description="The estimated time required for a professional to dismantle the product into recyclable components. Useful for assessing the economic viability of recycling. Example: 15"
    )

    # ==========================
    # INSTRUCTIONS
    # ==========================
    general_instructions: str = Field(
        description="High-level summary text explaining the recycling process. This is the first text the consumer reads on the recycling tab. Example: 'Remove all buttons before placing in the textile bin.'"
    )

    safety_warning: Optional[str] = Field(
        default=None,
        description="Critical safety information regarding disassembly or disposal. Must be displayed prominently if populated. Example: 'Do not puncture the battery compartment.'"
    )

    # Relationships
    version: "ProductVersion" = Relationship(back_populates="recycling_info")
    stages: List["ProductVersionRecyclingStage"] = Relationship(
        back_populates="recycling_info")


class ProductVersionRecyclingStage(TimestampMixin, SoftDeleteMixin, SQLModel, table=True):
    """
    Represents a specific, ordered step in the recycling or disassembly process.
    This model acts as the 'Container' or 'Header' for a specific action (e.g., 'Step 1: Remove Battery').
    It does not contain the detailed instructions itself; instead, it holds a sorted list of
    'ProductVersionRecyclingStageContent' blocks, allowing for a rich, mixed-media tutorial format.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="The unique identifier for this recycling stage."
    )
    recycling_info_id: uuid.UUID = Field(
        foreign_key="productversionrecycling.id",
        index=True,
        description="The parent recycling information block this stage belongs to."
    )

    step_order: int = Field(
        description="The numeric sequence (1-based index). WARNING: This list implies strict ordering. "
                    "BACKEND RESPONSIBILITY: On DELETE of step N, the Backend service MUST strictly decrement "
                    "the 'step_order' of all sibling stages where step_order > N to prevent integer gaps (orphan indexes)."
    )

    title: str = Field(
        description="The headline or short title of the action. Example: 'Battery Removal' or 'Separating Textiles'."
    )

    summary: Optional[str] = Field(
        default=None,
        description="A brief, high-level preview of this step, used for 'Table of Contents' or collapsed views. Detailed instructions should go into the content blocks."
    )

    estimated_duration_seconds: Optional[int] = Field(
        default=None,
        description="Optional metadata indicating how long this specific step typically takes to complete. Example: 120 (for 2 minutes)."
    )

    # Relationships
    recycling_info: "ProductVersionRecycling" = Relationship(
        back_populates="stages")

    # The rich content stream
    content_blocks: List["ProductVersionRecyclingStageContent"] = Relationship(
        back_populates="stage",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class ProductVersionRecyclingStageContent(TimestampMixin, SoftDeleteMixin, SQLModel, table=True):
    """
    A versatile content unit attached to a Recycling Stage.
    This model allows the creation of rich, mixed-media guides by treating content as a stream of blocks.
    A block can be a paragraph of text, an image, a video, or a safety warning, arranged in a specific order.
    Inherits SoftDeleteMixin to ensure audit safety if a supplier revises the instructions.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique ID for this content block."
    )
    stage_id: uuid.UUID = Field(
        foreign_key="productversionrecyclingstage.id",
        index=True,
        description="The parent Stage this content belongs to."
    )

    # ==========================
    # BLOCK CONFIGURATION
    # ==========================
    content_type: StageContentType = Field(
        description="The type of content contained in this block (e.g., 'text_block', 'video'). Determines which fields below should be read and how it renders."
    )

    display_order: int = Field(
        default=0,
        description="Sorting order within the stage. "
                    "BACKEND RESPONSIBILITY: Treat as a Doubly Linked List logic. If an item is moved from "
                    "Order 2 to Order 5, the Backend must efficiently re-index the affected intermediate rows. "
                    "Frontend relies on this integer being gapless for 'Previous/Next' logic."
    )

    # ==========================
    # DATA FIELDS (Nullable based on Type)
    # ==========================
    text_content: Optional[str] = Field(
        default=None,
        description="The body text for 'text_block' or 'warning_block' types. Also acts as the caption/alt-text for media types. Markdown formatting is supported."
    )

    file_url: Optional[str] = Field(
        default=None,
        description="The secure URL to the media file. Required if content_type is 'image', 'video', or 'document'. Null for pure text blocks."
    )

    file_name: Optional[str] = Field(
        default=None,
        description="The original filename for administrative tracking and audit logs. Example: 'step1_diagram.png'."
    )

    file_size_mb: Optional[float] = Field(
        default=None,
        description="Metadata for the file size in Megabytes. Useful for frontend loading indicators or 'Download PDF' buttons."
    )

    # Relationships
    stage: ProductVersionRecyclingStage = Relationship(
        back_populates="content_blocks")


# ==============================================================================
# 9. COLLABORATION & WORKFLOW
# ==============================================================================

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

    # NEW FIELDS
    due_date: Optional[date] = Field(
        default=None,
        description="The deadline for the supplier to submit data."
    )

    request_note: Optional[str] = Field(
        default=None,
        description="The initial instruction sent by the brand when creating the request."
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


# ==============================================================================
# 10. FRONTEND TEMPLATING
# ==============================================================================

class DPPTemplate(TimestampMixin, SoftDeleteMixin, SQLModel, table=True):
    """
    Defines the visual structure, layout, and styling of the Digital Product Passport (Landing Page).

    This acts as a 'Theme' or 'CMS Template'. Brands can start from a 'System Default',
    clone it, and customize it to match their branding.

    It separates 'Structure' (which widgets appear where) from 'Style' (colors, fonts),
    allowing for deep customization while maintaining data integrity.
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Unique identifier for this template."
    )
    tenant_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="tenant.id",
        description="The Brand that owns this custom template. If NULL, it is a System Global Template available to everyone."
    )

    # ==========================
    # LINEAGE & CLONING
    # ==========================
    source_template_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="dpptemplate.id",
        description="If this template was cloned from another (e.g., a System Default), this tracks the parent. Useful for resetting changes or tracking popularity."
    )

    is_system_default: bool = Field(
        default=False,
        description="Flag indicating if this is a platform-provided template. System templates cannot be edited directly by users; they must be cloned first."
    )

    # ==========================
    # METADATA (For the UI Library)
    # ==========================
    name: str = Field(
        index=True,
        description="The display name of the template. Example: 'Summer 2025 Eco-Dark Theme'."
    )

    description: Optional[str] = Field(
        default=None,
        description="Internal notes explaining the use case of this template. Example: 'High-contrast theme designed for the Outdoor Jacket line.'"
    )

    category: TemplateCategory = Field(
        default=TemplateCategory.GENERIC,
        description="High-level categorization to help users filter templates in the library. Example: 'minimalist'."
    )

    thumbnail_url: Optional[str] = Field(
        default=None,
        description="URL to a screenshot or preview image of this template. Crucial for the 'Select Template' grid view in the frontend."
    )

    version_label: str = Field(
        default="v1.0",
        description="User-defined version string for their own template management. Example: 'v2.1 - Added Video Widget'."
    )

    # ==========================
    # BUILDER CONFIGURATION
    # ==========================
    layout_config: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB),  # Enables Binary JSON support in PG
        description="Structure definition (JSON)."
    )

    style_config: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB),
        description="Theme definition (JSON)."
    )

    custom_css: Optional[str] = Field(
        default=None,
        description="Advanced field allowing raw CSS injection for Brands that need pixel-perfect overrides beyond the standard config."
    )

    # ==========================
    # STATUS
    # ==========================
    is_active: bool = Field(
        default=True,
        description="If False, this template is hidden from the selection menu but preserved for existing DPPs using it."
    )

    # Relationships
    tenant: Optional["Tenant"] = Relationship(back_populates="dpp_templates")
    dpp_versions: List["DPPVersion"] = Relationship(back_populates="template")
    translatable_fields: List["DPPTemplateField"] = Relationship(
        back_populates="template")

    # Self-referential relationship for cloning lineage
    children_templates: List["DPPTemplate"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "DPPTemplate.id==DPPTemplate.source_template_id",
            "remote_side": "DPPTemplate.id"
        }
    )

    __table_args__ = (
        # Creates a GIN index on layout_config to allow fast queries like:
        # SELECT * FROM dpptemplate WHERE layout_config @> '{"header": {"type": "sticky"}}'
        Index("idx_dpptemplate_layout", "layout_config", postgresql_using="gin"),
        Index("idx_dpptemplate_style", "style_config", postgresql_using="gin"),
    )


class DPPTemplateField(TimestampMixin, SQLModel, table=True):
    """
    Defines the 'Translatable Keys' available within a specific DPPTemplate.
    Instead of guessing JSON keys, we explicitly define them here.

    Example: 
    - key: "carbon_section_title"
    - default_text: "Carbon Footprint"
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    template_id: uuid.UUID = Field(foreign_key="dpptemplate.id", index=True)

    key: str = Field(
        index=True,
        description=r"Technical identifier. MUST be lowercase, dot-notation. "
                    r"VALIDATION REGEX: ^[a-z0-9]+(\.[a-z0-9]+)*$. "
                    "Examples: 'header.title', 'specs.carbon'. "
                    "Inconsistent naming prevents proper nested JSON mapping in the frontend."
    )

    field_type: TemplateFieldType = Field(
        default=TemplateFieldType.TEXT,
        description="Context hint for the translator/CMS. Ensures a Translator does not attempt "
                    "to translate a Color Code or a Database Number Format."
    )

    description: Optional[str] = Field(
        description="Helper text for the translator explaining context (e.g., 'Header for the weight section')."
    )

    default_text: str = Field(
        description="The fallback text if no translation is provided."
    )

    # Relationships
    template: "DPPTemplate" = Relationship(
        back_populates="translatable_fields")
    translations: List["DPPLocalizationEntry"] = Relationship(
        back_populates="field",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


# ==============================================================================
# 11. DIGITAL PRODUCT PASSPORT (PUBLIC ENTITY)
# ==============================================================================

class DPP(TimestampMixin, SoftDeleteMixin, SQLModel, table=True):
    """
    The Master Router and Identity for the Digital Product Passport (DPP).

    Now enhanced with:
    1. Relation to 'access_rules' for granular security.
    2. Relation to 'routing_logic' for dynamic version switching based on geography.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenant.id", index=True)
    product_id: uuid.UUID = Field(
        foreign_key="product.id", unique=True, index=True)

    # Identity
    public_uid: str = Field(unique=True, index=True)
    target_url: str = Field()
    qr_image_url: Optional[str] = Field(default=None)
    qr_style_config: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)

    # Routing
    # This acts as the "Global Default" if no specific RoutingLogic is matched.
    default_dpp_version_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("dppversion.id", use_alter=True,
                       name="fk_dpp_default_version"),
            nullable=True
        ),
        description="The fallback version to show if no geo-specific routing rules match the user's context."
    )

    status: DPPLifecycleStatus = Field(
        default=DPPLifecycleStatus.DRAFT_CONTAINER)

    # Analytics
    total_scans: int = Field(default=0)
    last_scanned_at: Optional[datetime] = Field(default=None)

    # Relationships
    tenant: "Tenant" = Relationship(back_populates="passports")
    product: "Product" = Relationship(back_populates="passport")

    # All historical versions
    versions: List["DPPVersion"] = Relationship(
        back_populates="passport",
        sa_relationship_kwargs={"cascade": "all, delete-orphan",
                                "primaryjoin": "DPP.id==DPPVersion.passport_id"}
    )

    # NEW: Dynamic Engines
    access_rules: List["DPPAccessRule"] = Relationship(
        back_populates="passport", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    routing_logic: List["DPPRoutingLogic"] = Relationship(
        back_populates="passport", sa_relationship_kwargs={"cascade": "all, delete-orphan"})


class DPPAccessRule(TimestampMixin, SoftDeleteMixin, SQLModel, table=True):
    """
    Defines a granular security rule for a Passport.

    SECURITY & PRIORITY LOGIC:
    1. EVALUATION ORDER:
       - Rules are evaluated based on 'priority' (Highest to Lowest).
       - The FIRST rule that matches the user's context (e.g., User is in France) applies.
       - Execution stops after the first match.

    2. COLLISION WARNING (App Layer Validation Required):
       - The Database does NOT enforce unique priorities because 'Soft Deletes' 
         leave 'deleted' rows with duplicate priorities.
       - APPLICATION LOGIC MUST ensure that for a single 'passport_id', 
         no two ACTIVE rules share the same 'priority'.
       - If a collision occurs (two rules with priority 10), the behavior is non-deterministic 
         and constitutes a security risk.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    passport_id: uuid.UUID = Field(
        foreign_key="dpp.id", index=True)

    rule_type: AccessRuleType = Field(
        description="The type of logic to apply. Example: 'geo_block'."
    )

    is_active: bool = Field(
        default=True,
        description="Switch to toggle this rule without deleting it."
    )

    priority: int = Field(
        default=0,
        description="Order of evaluation. Higher numbers override lower numbers."
    )

    # Payload
    rule_config: Dict[str, Any] = Field(
        default_factory=dict,
        sa_type=JSON,
        description="""
        Dynamic configuration based on rule_type.
        Examples:
        - GEO_ALLOW: {"countries": ["FR", "DE", "IT"]}
        - PASSWORD: {"hash": "sha256...", "hint": "See label"}
        - TIME_WINDOW: {"start": "2025-01-01", "end": "2026-01-01"}
        """
    )

    passport: "DPP" = Relationship(
        back_populates="access_rules")


class DPPRoutingLogic(TimestampMixin, SoftDeleteMixin, SQLModel, table=True):
    """
    Dynamic Routing Engine.
    Determines WHICH 'DPPVersion' to show based on the user's context (Location, Device, User-Agent).

    Scenario:
    A product is sold globally.
    - Users in France MUST see the 'EU Compliance Version' (V2).
    - Users in USA see the 'Standard Version' (V1).
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    passport_id: uuid.UUID = Field(
        foreign_key="dpp.id", index=True)

    target_version_id: uuid.UUID = Field(
        foreign_key="dppversion.id",
        description="The specific version snapshot to serve if the condition is met."
    )

    condition_country_codes: Optional[List[str]] = Field(
        default=None,
        sa_type=JSON,
        description="List of ISO codes. If user is here, show this version. Example: ['FR', 'DE']."
    )

    priority: int = Field(
        default=10,
        description="Evaluation order. Specific country rules should have higher priority than defaults."
    )

    passport: "DPP" = Relationship(
        back_populates="routing_logic")
    target_version: "DPPVersion" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "DPPRoutingLogic.target_version_id"})


# ==============================================================================
# 12. PUBLIC CONTENT PUBLISHING
# ==============================================================================

class DPPVersion(TimestampMixin, SoftDeleteMixin, SQLModel, table=True):
    """
    Represents a specific, immutable publication state (Snapshot).
    Now enhanced with 'localizations' to support multi-language displays
    from a single data source.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    passport_id: uuid.UUID = Field(foreign_key="dpp.id")
    source_product_version_id: uuid.UUID = Field(
        foreign_key="productversion.id")
    template_id: uuid.UUID = Field(foreign_key="dpptemplate.id")

    # Version Metadata
    version_number: int = Field()
    version_label: str = Field(default="Release")
    status: DPPVersionStatus = Field(default=DPPVersionStatus.DRAFT)
    change_log: Optional[str] = Field(default=None)

    # The Data
    data_snapshot: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)

    # SEO
    meta_title: Optional[str] = Field(default=None)
    meta_description: Optional[str] = Field(default=None)
    social_share_image_url: Optional[str] = Field(default=None)

    # Audit
    published_by_user_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="user.id")
    published_at: Optional[datetime] = Field(default=None)

    # Relationships
    passport: DPP = Relationship(
        back_populates="versions",
        sa_relationship_kwargs={
            "foreign_keys": "[DPPVersion.passport_id]"
        }
    )
    template: DPPTemplate = Relationship(back_populates="dpp_versions")
    source_product_version: "ProductVersion" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "DPPVersion.source_product_version_id"})

    # NEW: Localization
    localizations: List["DPPVersionLocalization"] = Relationship(
        back_populates="version",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class DPPVersionLocalization(TimestampMixin, SoftDeleteMixin, SQLModel, table=True):
    """
    Represents a supported language for a specific DPP Version.
    Acts as a container for the specific text entries.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    version_id: uuid.UUID = Field(foreign_key="dppversion.id", index=True)

    language_code: str = Field(description="ISO 639-1 code (e.g., 'fr').")
    is_default: bool = Field(default=False)

    # Relationships
    version: "DPPVersion" = Relationship(back_populates="localizations")

    # The actual text values
    entries: List["DPPLocalizationEntry"] = Relationship(
        back_populates="localization",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class DPPLocalizationEntry(TimestampMixin, SQLModel, table=True):
    """
    The specific translated text value for a specific field in a specific language.

    ADVANTAGE:
    - Integrity: You cannot translate a key that doesn't exist in the Template (Foreign Key constraint).
    - Maintenance: If you rename a field in the template, you update the 'DPPTemplateField' record, 
      and the links remain valid (unlike JSON where you'd have to parse strings).
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    localization_id: uuid.UUID = Field(
        foreign_key="dppversionlocalization.id",
        index=True,
        description="The parent language container."
    )

    template_field_id: uuid.UUID = Field(
        foreign_key="dpptemplatefield.id",
        index=True,
        description="The specific UI element being translated."
    )

    translated_text: str = Field(
        description="The actual content to display (e.g., 'Empreinte Carbone')."
    )

    # Relationships
    localization: DPPVersionLocalization = Relationship(
        back_populates="entries")
    field: DPPTemplateField = Relationship(back_populates="translations")


# ==============================================================================
# 13. SYSTEM INTEGRITY
# ==============================================================================

class SystemAuditLog(TimestampMixin, SQLModel, table=True):
    """
    Centralized ledger of all critical actions. 
    This is NOT for debugging; it is for Legal Compliance and Security.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: Optional[uuid.UUID] = Field(foreign_key="tenant.id", index=True)
    actor_user_id: Optional[uuid.UUID] = Field(
        foreign_key="user.id", index=True)

    # Context
    entity_type: str = Field(
        index=True, description="e.g., 'ProductVersion', 'DPP'")
    entity_id: uuid.UUID = Field(index=True)

    action: AuditAction = Field()

    # Data Changes (Store diffs)
    changes: Dict[str, Any] = Field(
        default_factory=dict, sa_type=JSON, description="{'field': {'old': 'A', 'new': 'B'}}")

    ip_address: Optional[str] = Field(default=None)
    user_agent: Optional[str] = Field(default=None)

    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
