from typing import Optional, List
from datetime import datetime
import uuid
from sqlmodel import SQLModel, Field, Relationship
from enum import Enum


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
