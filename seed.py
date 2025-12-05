from loguru import logger
from sqlmodel import Session, select
from app.db.core import engine
from app.db.schema import (
    Role, Permission, RolePermissionLink,
    SubscriptionPlan, Feature, PlanFeatureLink
)


# 1. Define all valid system permissions
SYSTEM_PERMISSIONS = {
    "tenant:update": "Can update tenant settings/branding",
    "tenant:delete": "Can delete the entire workspace",
    "billing:read": "Can view invoices and subscription status",
    "billing:update": "Can change credit cards or subscription plans",
    "member:invite": "Can invite new members",
    "member:update": "Can change member roles",
    "member:delete": "Can remove members",
    "project:create": "Can create new projects",
    "project:delete": "Can delete projects",
    "project:read": "Can view projects",
}

# 2. Define Roles and map them to permission keys
GLOBAL_ROLES = {
    "Owner": [
        "tenant:update", "tenant:delete",
        "billing:read", "billing:update",
        "member:invite", "member:update", "member:delete",
        "project:create", "project:delete", "project:read"
    ],
    "Admin": [
        "tenant:update",
        "member:invite", "member:update", "member:delete",
        "project:create", "project:delete", "project:read"
        # Admins usually can't delete the tenant or change billing
    ],
    "Member": [
        "project:create", "project:read"
    ],
    "Viewer": [
        "project:read"
    ]
}

# 3. Define Default Plans
DEFAULT_PLANS = [
    {
        "name": "Free Tier",
        "price": 0.0,
        "is_personal_only": False,
        "features": {
            "max_members": "5",
            "max_projects": "3",
            "audit_logs": "false"
        }
    },
    {
        "name": "Pro",
        "price": 29.00,
        "is_personal_only": False,
        "features": {
            "max_members": "unlimited",
            "max_projects": "unlimited",
            "audit_logs": "true"
        }
    }
]


def seed_permissions(session: Session) -> dict[str, Permission]:
    """Creates permissions if they don't exist. Returns a dict map of key -> Permission."""
    logger.info("--- Seeding Permissions ---")
    perm_map = {}

    for key, desc in SYSTEM_PERMISSIONS.items():
        permission = session.exec(
            select(Permission).where(Permission.key == key)).first()
        if not permission:
            permission = Permission(key=key, description=desc)
            session.add(permission)
            logger.info(f"Created Permission: {key}")
        else:
            logger.info(f"Existing Permission: {key}")

        # Add to session to ensure IDs are generated if new
        session.flush()
        perm_map[key] = permission

    return perm_map


def seed_roles(session: Session, perm_map: dict[str, Permission]):
    """Creates Global Roles and links them to Permissions."""
    logger.info("--- Seeding Roles ---")

    for role_name, perm_keys in GLOBAL_ROLES.items():
        # Check if role exists
        role = session.exec(select(Role).where(
            Role.name == role_name, Role.tenant_id == None)).first()

        if not role:
            # tenant_id=None means Global
            role = Role(name=role_name, tenant_id=None)
            session.add(role)
            session.flush()  # Flush to get role.id
            logger.info(f"Created Role: {role_name}")
        else:
            logger.info(f"Existing Role: {role_name}")

        # Sync Permissions (Idempotent: Remove old links, add defined ones)
        # In a strict production update, you might be more careful, but for seeding,
        # we ensure the role has EXACTLY the permissions defined in the config.

        # 1. Get current links
        current_links = session.exec(select(RolePermissionLink).where(
            RolePermissionLink.role_id == role.id)).all()
        existing_perm_ids = {link.permission_id for link in current_links}

        # 2. Calculate target permission IDs
        target_perm_ids = {perm_map[k].id for k in perm_keys if k in perm_map}

        # 3. Add missing links
        for perm_id in target_perm_ids:
            if perm_id not in existing_perm_ids:
                link = RolePermissionLink(
                    role_id=role.id, permission_id=perm_id)
                session.add(link)
                logger.info(f"  + Added permission {perm_id} to {role_name}")

        # 4. Remove extra links (Optional: strictly enforce seed config)
        # for link in current_links:
        #     if link.permission_id not in target_perm_ids:
        #         session.delete(link)


def seed_plans(session: Session):
    """Creates default Features and Subscription Plans."""
    logger.info("--- Seeding Plans & Features ---")

    for plan_data in DEFAULT_PLANS:
        # 1. Create or Get Plan
        plan = session.exec(select(SubscriptionPlan).where(
            SubscriptionPlan.name == plan_data["name"])).first()
        if not plan:
            plan = SubscriptionPlan(
                name=plan_data["name"],
                price=plan_data["price"],
                is_personal_only=plan_data["is_personal_only"]
            )
            session.add(plan)
            session.flush()
            logger.info(f"Created Plan: {plan.name}")

        # 2. Process Features
        features_config = plan_data["features"]
        for key, value in features_config.items():
            # Create Feature if missing
            feature = session.exec(
                select(Feature).where(Feature.key == key)).first()
            if not feature:
                feature = Feature(key=key, description=f"Controls {key}")
                session.add(feature)
                session.flush()

            # Link Plan <-> Feature with Value
            link = session.exec(
                select(PlanFeatureLink).where(
                    PlanFeatureLink.plan_id == plan.id,
                    PlanFeatureLink.feature_id == feature.id
                )
            ).first()

            if not link:
                link = PlanFeatureLink(
                    plan_id=plan.id,
                    feature_id=feature.id,
                    value=value
                )
                session.add(link)
            elif link.value != value:
                # Update value if changed in seed config
                link.value = value
                session.add(link)


def main():
    # Ensure tables exist (if not using Alembic)
    # SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        try:
            # 1. Permissions
            perm_map = seed_permissions(session)

            # 2. Roles
            seed_roles(session, perm_map)

            # 3. Plans
            seed_plans(session)

            session.commit()
            logger.info("Database seeding completed successfully.")

        except Exception as e:
            session.rollback()
            logger.error(f"Seeding failed: {e}")
            raise e


if __name__ == "__main__":
    main()
