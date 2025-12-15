from typing import Optional, List
from datetime import datetime, date
import uuid
from sqlmodel import SQLModel, Field, Relationship
from enum import Enum
from pydantic import PrivateAttr


class TenantStatus(str, Enum):
    """
    Defines the lifecycle state of a Tenant.

    Attributes:
        ACTIVE: The tenant is fully operational.
        SUSPENDED: Access is blocked (e.g., non-payment, TOS violation).
        ARCHIVED: Soft-deleted state, data preserved but not accessible.
    """
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class TenantType(str, Enum):
    """
    Defines the nature of the Tenant.

    Attributes:
        PERSONAL: A solo workspace automatically created for a user (1:1 with User).
        ORGANIZATION: A collaborative workspace that can have multiple members.
    """
    PERSONAL = "personal"
    ORGANIZATION = "organization"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    CANCELED = "canceled"
    PAST_DUE = "past_due"
    TRIALING = "trialing"


class InvitationStatus(str, Enum):
    """
    Tracks the lifecycle of an invitation link.
    """
    PENDING = "pending"   # Email sent, waiting for action.
    ACCEPTED = "accepted"  # User clicked link and joined.
    EXPIRED = "expired"   # Time limit passed (security).
    DECLINED = "declined"  # User explicitly rejected the invite.
    REVOKED = "revoked"   # Admin cancelled the invite before it was used.


class MemberStatus(str, Enum):
    """Controls access at the specific Tenant level."""
    ACTIVE = "active"
    INACTIVE = "inactive"


class MaterialType(str, Enum):
    NATURAL = "natural"
    SYNTHETIC = "synthetic"
    BLEND = "blend"
    SEMI_SYNTHETIC = "semi_synthetic"


class RecyclabilityClass(str, Enum):
    CLASS_A = "class_a"  # Monomaterial, easy to recycle
    CLASS_B = "class_b"  # Blended but separable
    CLASS_C = "class_c"  # Difficult to recycle
    CLASS_D = "class_d"  # Not recyclable / Energy recovery only


class SupplierRole(str, Enum):
    TIER_1_ASSEMBLY = "tier_1_assembly"       # Final product assembly
    TIER_2_FABRIC = "tier_2_fabric"           # Fabric production/dyeing
    TIER_3_FIBER = "tier_3_fiber"             # Yarn spinning/Fiber production


class DPPStatus(str, Enum):
    """
    Lifecycle of the Digital Product Passport.
    """
    DRAFT = "draft"         # Internal only, data being gathered
    PUBLISHED = "published"  # Live, QR code scans work
    SUSPENDED = "suspended"  # Temporarily disabled (e.g. recall investigation)
    ARCHIVED = "archived"   # Product EOL, historical record only


class DPPEventType(str, Enum):
    """
    Types of events recorded in the passport's audit log.
    """
    CREATED = "created"
    PUBLISHED = "published"
    UPDATED = "updated"
    SCANNED = "scanned"             # Public scan
    STATUS_CHANGE = "status_change"
    OWNERSHIP_TRANSFER = "ownership_transfer"  # For circular economy logic


class TimestampMixin(SQLModel):
    """Standardizes audit timestamps across tables."""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={
                                 "onupdate": datetime.utcnow})


class PlanFeatureLink(TimestampMixin, SQLModel, table=True):
    """
    Association model linking Subscription Plans to Features with a specific value.

    This acts as a pivot table that not only connects a plan to a feature
    but also defines *how much* of that feature the plan gets.

    Attributes:
        plan_id (UUID): Foreign key to the SubscriptionPlan.
        feature_id (UUID): Foreign key to the Feature.
        value (str): The logical value of the feature for this plan.
                     - For quotas: "5", "100", "unlimited"
                     - For booleans: "true", "false"
                     - For specific tiers: "gold_support"
    """
    plan_id: uuid.UUID = Field(
        foreign_key="subscriptionplan.id", primary_key=True)
    feature_id: uuid.UUID = Field(foreign_key="feature.id", primary_key=True)
    value: str = Field(
        default="true", description="The limit or state of the feature (e.g., '10', 'true').")


class RolePermissionLink(TimestampMixin, SQLModel, table=True):
    """
    Association model linking Roles to Permissions.

    This is a standard many-to-many pivot table used to construct
    Access Control Lists (ACLs).

    Attributes:
        role_id (UUID): Foreign key to the Role.
        permission_id (UUID): Foreign key to the Permission.
    """
    role_id: uuid.UUID = Field(foreign_key="role.id", primary_key=True)
    permission_id: uuid.UUID = Field(
        foreign_key="permission.id", primary_key=True)


class Feature(TimestampMixin, SQLModel, table=True):
    """
    Represents a specific system capability or gate.

    Features are the building blocks of subscription plans. They are not
    code permissions (RBAC), but rather business logic gates (e.g., "Can this
    tenant upload custom branding?", "How many projects can they create?").

    Attributes:
        id (UUID): Unique identifier.
        key (str): A unique slug used in code to check access (e.g., 'max_projects', 'sso_enabled').
        description (str): Human-readable explanation of what this feature controls.
        plans (List[SubscriptionPlan]): List of plans that include this feature.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    key: str = Field(index=True, unique=True,
                     description="The code reference key (e.g., 'audit_logs').")
    description: Optional[str] = Field(
        default=None, description="Internal description of the feature.")

    plans: List["SubscriptionPlan"] = Relationship(
        back_populates="features", link_model=PlanFeatureLink)


class SubscriptionPlan(TimestampMixin, SQLModel, table=True):
    """
    Represents a billing tier (SaaS Plan).

    Tenants subscribe to a plan, which dictates which Features are active
    and what limits are enforced via the PlanFeatureLink.

    Attributes:
        id (UUID): Unique identifier.
        name (str): Display name (e.g., "Free Tier", "Enterprise").
        price (float): Monthly cost in base currency.
        is_personal_only (bool): If True, this plan is hidden for Organization tenants
                                 and only available for Personal tenants.
        tenants (List[Tenant]): List of tenants currently on this plan.
        features (List[Feature]): List of features enabled for this plan.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(unique=True, description="Marketing name of the plan.")
    price: float = Field(default=0.0, description="Monthly price.")
    is_personal_only: bool = Field(
        default=False, description="Restricts plan to Personal workspaces only.")

    features: List["Feature"] = Relationship(
        back_populates="plans", link_model=PlanFeatureLink)
    subscriptions: List["TenantSubscription"] = Relationship(
        back_populates="plan")


class Permission(TimestampMixin, SQLModel, table=True):
    """
    Represents an atomic authorization rule.

    These are high-granularity keys used by the backend to verify if a user
    can perform a specific API action.

    Attributes:
        id (UUID): Unique identifier.
        key (str): The unique action string (e.g., 'user:create', 'billing:read').
        roles (List[Role]): The roles that possess this permission.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    key: str = Field(unique=True, index=True,
                     description="The permission slug (e.g., 'project:delete').")

    roles: List["Role"] = Relationship(
        back_populates="permissions", link_model=RolePermissionLink)


class Role(TimestampMixin, SQLModel, table=True):
    """
    Represents a collection of permissions (A Job Function).

    Roles can be Global (System Defined) or Custom (Tenant Defined).

    *   **Global Role**: `tenant_id` is NULL. Available to be assigned in ANY tenant.
        (e.g., 'Owner', 'Admin', 'Viewer').
    *   **Custom Role**: `tenant_id` is set. Only available within that specific tenant.
        (e.g., 'Junior Editor' defined by Acme Corp).

    Attributes:
        id (UUID): Unique identifier.
        name (str): Display name of the role.
        tenant_id (UUID, Optional): Scope of the role. None = Global, UUID = Private to Tenant.
        permissions (List[Permission]): The list of allowed actions.
        memberships (List[TenantMember]): Users who hold this role in specific tenants.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(description="Display name (e.g., 'Admin').")
    tenant_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="tenant.id", description="NULL for Global roles, Set for Custom roles.")

    permissions: List["Permission"] = Relationship(
        back_populates="roles", link_model=RolePermissionLink)
    memberships: List["TenantMember"] = Relationship(back_populates="role")
    tenant: Optional["Tenant"] = Relationship(back_populates="custom_roles")


class User(TimestampMixin, SQLModel, table=True):
    """
    Represents a Global User Identity.

    The User model holds authentication data and profile information. 
    It is agnostic of Tenants. A user has no permissions until they are 
    linked to a Tenant via TenantMember.

    Attributes:
        id (UUID): Unique identifier.
        email (str): Unique signin email.
        hashed_password (str): Securely stored password hash.
        first_name (str): User's given name.
        last_name (str): User's family name.
        is_active (bool): Global kill-switch for the user account.
        memberships (List[TenantMember]): List of tenants this user belongs to.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(unique=True, index=True,
                       description="User's signin email.")
    hashed_password: str = Field(description="Bcrypt/Argon2 password hash.")

    first_name: Optional[str] = Field(default=None, description="First name.")
    last_name: Optional[str] = Field(default=None, description="Last name.")

    is_active: bool = Field(
        default=True, description="If false, user cannot log in anywhere.")

    memberships: List["TenantMember"] = Relationship(back_populates="user")

    # non db field
    _tenant_id: Optional[uuid.UUID] = PrivateAttr(None)

    sent_invitations: List["TenantInvitation"] = Relationship(
        back_populates="inviter",
        sa_relationship_kwargs={
            "primaryjoin": "TenantInvitation.inviter_id==User.id"}
    )

    received_invitations: List["TenantInvitation"] = Relationship(
        back_populates="invitee",
        sa_relationship_kwargs={
            "primaryjoin": "TenantInvitation.invitee_id==User.id"}
    )


class Tenant(TimestampMixin, SQLModel, table=True):
    """
    Represents an isolated environment (Company or Personal Workspace).

    This is the core of the multi-tenancy. All business data (projects, tasks, etc.)
    should have a foreign key to this table.

    Note on Personal Accounts:
    If `type` is PERSONAL, this represents a single user's private workspace. 
    Logic should enforce that Personal tenants cannot have >1 member.

    Attributes:
        id (UUID): Unique identifier.
        name (str): Display name (e.g., "Acme Inc" or "John's Workspace").
        slug (str): Unique URL-safe identifier (e.g., "acme-inc").
        type (TenantType): Distinguishes between Personal and Organization workspaces.
        status (TenantStatus): Billing/Ban status.
        plan_id (UUID): Foreign key to the current Subscription Plan.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(description="Organization name or Workspace name.")
    slug: str = Field(unique=True, index=True,
                      description="URL-friendly identifier.")

    type: TenantType = Field(
        default=TenantType.ORGANIZATION, description="Personal or Organization.")
    status: TenantStatus = Field(
        default=TenantStatus.ACTIVE, description="Lifecycle status.")

    subscription: Optional["TenantSubscription"] = Relationship(
        sa_relationship_kwargs={"uselist": False}, back_populates="tenant"
    )

    members: List["TenantMember"] = Relationship(back_populates="tenant")
    custom_roles: List["Role"] = Relationship(back_populates="tenant")
    invitations: List["TenantInvitation"] = Relationship(
        back_populates="tenant")

    products: List["Product"] = Relationship(back_populates="tenant")
    suppliers: List["Supplier"] = Relationship(back_populates="tenant")

    custom_materials: List["Material"] = Relationship(back_populates="tenant")
    custom_certifications: List["Certification"] = Relationship(
        back_populates="tenant")


class TenantSubscription(TimestampMixin, SQLModel, table=True):
    """
    Separates the Billing lifecycle from the Tenant identity.
    Allows for tracking trial ends, cancellations, and external payment IDs.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # One active sub per tenant
    tenant_id: uuid.UUID = Field(foreign_key="tenant.id", unique=True)
    plan_id: uuid.UUID = Field(foreign_key="subscriptionplan.id")

    status: SubscriptionStatus = Field(default=SubscriptionStatus.ACTIVE)
    current_period_end: datetime = Field(
        description="When the current billing cycle ends.")
    stripe_subscription_id: Optional[str] = Field(default=None, index=True)

    tenant: Tenant = Relationship(back_populates="subscription")
    plan: SubscriptionPlan = Relationship(back_populates="subscriptions")


class TenantMember(TimestampMixin, SQLModel, table=True):
    """
    Represents the Membership (Pivot) between a User and a Tenant.

    This is the authorization context. It defines:
    1. Authorization: Is the user inside this tenant? (Existence of record)
    2. Access Control: What can they do? (Linked Role)

    Attributes:
        id (UUID): Unique identifier.
        user_id (UUID): Foreign key to the User.
        tenant_id (UUID): Foreign key to the Tenant.
        role_id (UUID): Foreign key to the Role assigned to this user in this tenant.
        joined_at (datetime): Timestamp when user was added to the tenant.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", description="The member.")
    tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id", description="The organization.")
    role_id: uuid.UUID = Field(
        foreign_key="role.id", description="The assigned permissions.")

    joined_at: datetime = Field(default_factory=datetime.utcnow)

    status: MemberStatus = Field(default=MemberStatus.ACTIVE)

    user: User = Relationship(back_populates="memberships")
    tenant: Tenant = Relationship(back_populates="members")
    role: Role = Relationship(back_populates="memberships")


class TenantInvitation(TimestampMixin, SQLModel, table=True):
    """
    Represents a secure, time-bound request for a user to join a Tenant.

    This model bridges the gap between an "outsider" (someone with just an email)
    and an "insider" (a TenantMember).

    ## The Invitation Flow:
    1. **Creation**: An existing member (`inviter_id`) triggers an invite for an `email`.
    2. **Resolution**: 
       - If a `User` already exists with that email, `invitee_id` can be pre-filled 
         or resolved upon lookup.
       - If no `User` exists, `invitee_id` remains NULL until they register.
    3. **Consumption**: When the link is clicked (validating `token`), a new 
       `TenantMember` record is created, and this invitation status becomes 'ACCEPTED'.

    Attributes:
        id (UUID): Unique system identifier for this record.
        email (str): The specific email address authorized to join.
                     (Security Note: The token should only work for this specific email).
        token (str): A high-entropy, URL-safe string sent to the user. 
                     Do not use the UUID `id` for public links.
        status (InvitationStatus): Current state of the invite.
        expires_at (datetime): Absolute timestamp when this link becomes invalid.

        tenant_id (UUID): The Workspace/Organization the user is being invited to.
        role_id (UUID): The permission set pre-selected for this user upon joining.

        inviter_id (UUID): The ID of the existing user who sent the invitation 
                           (useful for audit logs: "Who let this person in?").
        invitee_id (UUID, Optional): The ID of the target user, if they already have 
                                     an account. If NULL, they must sign up first.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    # Target Information
    email: str = Field(
        index=True, description="The email address of the person being invited.")

    # Security & Lifecycle
    token: str = Field(unique=True, index=True,
                       description="Cryptographic token for the invitation URL.")
    status: InvitationStatus = Field(
        default=InvitationStatus.PENDING, description="State of the invitation.")
    expires_at: datetime = Field(
        description="Date when the invitation token becomes invalid.")

    # Context
    tenant_id: uuid.UUID = Field(
        foreign_key="tenant.id", description="The target workspace.")
    role_id: uuid.UUID = Field(
        foreign_key="role.id", description="The role the user will receive upon acceptance.")

    # Actors
    inviter_id: uuid.UUID = Field(
        foreign_key="user.id", description="The existing member who sent the invite.")
    invitee_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="user.id", description="The receiver, if they already exist in the system.")

    # Relationships
    tenant: "Tenant" = Relationship(back_populates="invitations")

    inviter: "User" = Relationship(
        back_populates="sent_invitations",
        sa_relationship_kwargs={"foreign_keys": "TenantInvitation.inviter_id"}
    )

    invitee: Optional["User"] = Relationship(
        back_populates="received_invitations",
        sa_relationship_kwargs={"foreign_keys": "TenantInvitation.invitee_id"}
    )


class Material(TimestampMixin, SQLModel, table=True):
    """
    Lookup table for raw materials (Cotton, Elastane, Recycled Polyester).
    Can be Global (System defined, tenant_id=None) or Tenant Custom.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="tenant.id", description="Null for Global/System materials.")

    code: str = Field(unique=True, index=True,
                      description="Unique standard code (e.g. ISO code or Internal ERP code).")
    name: str = Field(index=True)
    material_type: MaterialType

    # Backpopulates
    product_links: List["ProductMaterialLink"] = Relationship(
        back_populates="material")
    tenant: Tenant = Relationship(back_populates="custom_materials")


class Certification(TimestampMixin, SQLModel, table=True):
    """
    Lookup table for sustainability standards (GOTS, Oeko-Tex, Cradle2Cradle).
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="tenant.id")

    code: str = Field(unique=True, index=True,
                      description="Unique certification identifier.")
    name: str
    issuer: str = Field(
        description="Organization issuing the cert (e.g. 'Global Standard gGmbH').")

    product_links: List["ProductCertificationLink"] = Relationship(
        back_populates="certification")
    tenant: Tenant = Relationship(back_populates="custom_certifications")


class Supplier(TimestampMixin, SQLModel, table=True):
    """
    A factory or vendor in the tenant's supply chain.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenant.id", index=True)

    name: str
    location_country: str = Field(index=True)
    facility_address: Optional[str] = None
    social_audit_rating: Optional[str] = Field(
        default=None, description="Summary of social compliance (e.g. SA8000).")

    # Relationships
    product_links: List["ProductSupplierLink"] = Relationship(
        back_populates="supplier")
    tenant: Tenant = Relationship(back_populates="suppliers")


class Product(TimestampMixin, SQLModel, table=True):
    """
    The Core Clothing Item (SKU/Model).
    Contains Identification and Manufacturing basics.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenant.id", index=True)

    # 1. Identification
    gtin: Optional[str] = Field(
        default=None, index=True, description="Global Trade Item Number (EAN/UPC).")
    batch_number: Optional[str] = Field(
        default=None, description="Specific production run for traceability.")
    name: str = Field(description="Commercial product name.")
    model_reference: str = Field(
        index=True, description="Internal model number/SKU.")
    brand_name: str = Field(description="Brand name displayed on label.")

    # 2. Manufacturing
    manufacturing_country: str = Field(
        description="Country of final assembly.")
    manufacture_date: Optional[date] = Field(
        default=None, description="Month/Year of production.")

    # 3. End-of-Life Instructions
    care_instructions: Optional[str] = Field(
        default=None, description="Washing/Drying symbols or text.")
    disposal_instructions: Optional[str] = Field(
        default=None, description="Recycling bin instructions.")

    # Relationships
    tenant: Tenant = Relationship(back_populates="products")

    durability: Optional["ProductDurability"] = Relationship(
        sa_relationship_kwargs={
            "uselist": False,
            "cascade": "all, delete-orphan"
        },
        back_populates="product"
    )

    environmental: Optional["ProductEnvironmental"] = Relationship(
        sa_relationship_kwargs={
            "uselist": False,
            "cascade": "all, delete-orphan"
        },
        back_populates="product"
    )

    materials: List["ProductMaterialLink"] = Relationship(
        back_populates="product",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    suppliers: List["ProductSupplierLink"] = Relationship(
        back_populates="product",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    certifications: List["ProductCertificationLink"] = Relationship(
        back_populates="product",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    spare_parts: List["SparePart"] = Relationship(
        back_populates="product",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    passport: Optional["DigitalProductPassport"] = Relationship(
        sa_relationship_kwargs={
            "uselist": False,  # Enforces One-to-One on the ORM side
            "cascade": "all, delete-orphan"
        },
        back_populates="product"
    )


class ProductDurability(TimestampMixin, SQLModel, table=True):
    """
    ESPR Requirement: Circularity & Durability Metrics.
    Separated to keep the main Product table clean (3NF / Domain separation).
    """
    product_id: uuid.UUID = Field(foreign_key="product.id", primary_key=True)

    # Physical Durability
    pilling_resistance_grade: Optional[float] = Field(
        default=None, description="ISO grade 1-5.")
    color_fastness_grade: Optional[float] = None
    dimensional_stability_percent: Optional[float] = Field(
        default=None, description="Shrinkage rate.")
    zipper_durability_cycles: Optional[int] = None

    # Repair & Circularity
    repairability_score: Optional[float] = Field(
        default=None, description="Index 0-10.")
    repair_instructions_url: Optional[str] = None
    recyclability_class: Optional[RecyclabilityClass] = None

    product: Product = Relationship(back_populates="durability")


class ProductEnvironmental(TimestampMixin, SQLModel, table=True):
    """
    ESPR Requirement: Product Environmental Footprint (PEF).
    """
    product_id: uuid.UUID = Field(foreign_key="product.id", primary_key=True)

    # Footprint Data
    carbon_footprint_kg_co2e: Optional[float] = None
    water_usage_liters: Optional[float] = None
    energy_consumption_mj: Optional[float] = None

    # Chemical & Safety
    microplastic_shedding_rate: Optional[str] = Field(
        default=None, description="e.g. 'Low', 'Medium'.")
    substances_of_concern_present: bool = Field(
        default=False, description="Contains SVHCs?")
    soc_declaration_url: Optional[str] = None

    product: Product = Relationship(back_populates="environmental")


class SparePart(TimestampMixin, SQLModel, table=True):
    """
    Availability of spare parts for repairability compliance.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    product_id: uuid.UUID = Field(foreign_key="product.id")

    part_name: str
    ordering_code: str
    is_available: bool = True

    product: Product = Relationship(back_populates="spare_parts")


class ProductMaterialLink(TimestampMixin, SQLModel, table=True):
    """
    Links Product to Material with composition details.
    Example: 95% Organic Cotton (Turkey).
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    product_id: uuid.UUID = Field(foreign_key="product.id")
    material_id: uuid.UUID = Field(foreign_key="material.id")

    percentage: float = Field(
        description="Composition percentage (e.g. 95.0).")
    is_recycled: bool = Field(default=False)
    origin_country: Optional[str] = Field(
        default=None, description="Origin of this specific fiber batch.")

    product: Product = Relationship(back_populates="materials")
    material: Material = Relationship(back_populates="product_links")


class ProductSupplierLink(TimestampMixin, SQLModel, table=True):
    """
    Supply Chain Mapping (Traceability).
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    product_id: uuid.UUID = Field(foreign_key="product.id")
    supplier_id: uuid.UUID = Field(foreign_key="supplier.id")

    role: SupplierRole = Field(
        description="Tier/Role of this supplier for this product.")

    product: Product = Relationship(back_populates="suppliers")
    supplier: Supplier = Relationship(back_populates="product_links")


class ProductCertificationLink(TimestampMixin, SQLModel, table=True):
    """
    Links specific certificates to the product.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    product_id: uuid.UUID = Field(foreign_key="product.id")
    certification_id: uuid.UUID = Field(foreign_key="certification.id")

    certificate_number: str = Field(
        description="The specific license/cert number.")
    valid_until: Optional[date] = None
    digital_document_url: Optional[str] = None

    product: Product = Relationship(back_populates="certifications")
    certification: Certification = Relationship(back_populates="product_links")


class DigitalProductPassport(TimestampMixin, SQLModel, table=True):
    """
    The Digital Twin identity.

    This model represents the public-facing interface of the Product.
    It manages the "Key" (QR Code/URL) to access the "Value" (Product Data).

    Attributes:
        product_id: 1:1 Link to the internal product data.
        public_uid: A unique, non-guessable ID exposed in the URL (not the DB UUID).
                    Useful for GS1 Digital Link compliance.
        status: Controls public visibility.
        qr_code_url: Storage link to the generated QR image.
        target_url: The actual destination URL the QR points to.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    # Enforce 1:1 relationship with Product
    product_id: uuid.UUID = Field(foreign_key="product.id", unique=True)

    # Public Facing Identity
    public_uid: str = Field(
        unique=True,
        index=True,
        description="Public specific ID (e.g., for GS1 Digital Link path)."
    )

    status: DPPStatus = Field(default=DPPStatus.DRAFT)

    # Access details
    qr_code_url: Optional[str] = Field(
        default=None,
        description="URL to the stored QR code image (S3/Blob)."
    )
    target_url: str = Field(
        description="The resolved web link where the DPP is hosted."
    )

    # Versioning (Important for regulatory compliance)
    version: int = Field(
        default=1, description="Increments on significant data updates.")
    blockchain_hash: Optional[str] = Field(
        default=None,
        description="Optional hash if anchoring data to a blockchain for immutability."
    )

    # Relationships
    product: "Product" = Relationship(back_populates="passport")
    events: List["DPPEvent"] = Relationship(
        back_populates="passport",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    extra_details: List["DPPExtraDetail"] = Relationship(
        back_populates="passport",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class DPPEvent(SQLModel, table=True):
    """
    Audit Log / Journey for the Passport.

    Tracks when the passport was published, updated, or scanned.
    Essential for 'Provenance' requirements in DPP legislation.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    dpp_id: uuid.UUID = Field(
        foreign_key="digitalproductpassport.id", index=True)

    event_type: DPPEventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    description: Optional[str] = Field(default=None)

    # Location data (Optional, for supply chain events)
    location: Optional[str] = Field(description="City/Country or GPS coords.")

    # If the action was performed by a logged-in user
    actor_id: Optional[uuid.UUID] = Field(default=None, foreign_key="user.id")

    passport: DigitalProductPassport = Relationship(back_populates="events")


class DPPExtraDetail(TimestampMixin, SQLModel, table=True):
    """
    Key-Value store for Passport-specific attributes.

    Allows tenants to add custom fields to the Passport display 
    that aren't strictly part of the physical product schema.
    (e.g., "Marketing Story", "Video Link", "Warranty Terms").
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    dpp_id: uuid.UUID = Field(foreign_key="digitalproductpassport.id")

    key: str = Field(
        index=True, description="Display label (e.g. 'Warranty Info').")
    value: str = Field(description="Content or Link.")
    is_public: bool = Field(
        default=True, description="If false, visible only to regulators/auditors.")

    display_order: int = Field(default=0)

    passport: DigitalProductPassport = Relationship(
        back_populates="extra_details")
