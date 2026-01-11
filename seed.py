import uuid
import logging
from datetime import datetime
from sqlmodel import Session, select
from sqlalchemy.exc import IntegrityError

# Adjust these imports to match your project structure
from app.db.core import engine
from app.db.schema import (
    # Auth & Tenants
    Role, Permission, RolePermissionLink, Tenant, User, TenantMember,
    TenantType, TenantStatus, MemberStatus,
    # Master Data
    CertificateDefinition, CertificateCategory,
    MaterialDefinition, MaterialType,
    # Templates
    DPPTemplate, DPPTemplateField, TemplateCategory, TemplateFieldType,
    # Enums
    VisibilityScope
)

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==============================================================================
# 1. CONFIGURATION: PERMISSIONS
# ==============================================================================
SYSTEM_PERMISSIONS = {
    # Tenancy & Users
    "tenant:manage": "Full access to tenant settings",
    "users:invite": "Can invite new members to the tenant",
    "users:manage": "Can change member roles and permissions",

    # B2B Network
    "network:connect": "Can initiate connections with suppliers/brands",
    "network:audit": "Can view full supplier details",

    # Products (Brand Side)
    "product:create": "Can define new product shells",
    "product:delete": "Can remove products",
    "product:view": "Can view product registry",

    # Data Requests (Workflow)
    "request:create": "Can send data requests to suppliers",
    "request:approve": "Can approve/reject supplier data",
    "request:submit": "Can fill and submit data forms (Supplier side)",

    # Artifacts (Supplier Side)
    "artifact:upload": "Can upload certificates and documents",
    "artifact:delete": "Can delete private artifacts",

    # DPP Publishing
    "dpp:create": "Can create a passport draft",
    "dpp:publish": "Can set a passport to public/active",
    "dpp:archive": "Can decommission a passport",
    "dpp:analytics": "Can view scan metrics",
}

# ==============================================================================
# 2. CONFIGURATION: ROLES
# ==============================================================================
# These are Global Roles (tenant_id=None) available to all organizations.
GLOBAL_ROLES = {
    "System Admin": list(SYSTEM_PERMISSIONS.keys()),  # All permissions

    "Brand Owner": [
        "tenant:manage", "users:invite", "users:manage",
        "network:connect", "network:audit",
        "product:create", "product:delete", "product:view",
        "request:create", "request:approve",
        "dpp:create", "dpp:publish", "dpp:archive", "dpp:analytics"
    ],

    "Brand Manager": [
        "product:create", "product:view",
        "request:create", "request:approve",
        "dpp:create", "dpp:analytics"
    ],

    "Supplier Admin": [
        "tenant:manage", "users:invite",
        "network:connect",
        "request:submit",
        "artifact:upload", "artifact:delete"
    ],

    "Supplier Contributor": [
        "request:submit",
        "artifact:upload"
    ],

    "Auditor": [
        "network:audit", "product:view", "dpp:analytics"
    ]
}

# ==============================================================================
# 3. CONFIGURATION: MASTER DATA (Certificates & Materials)
# ==============================================================================
STANDARD_CERTIFICATES = [
    {
        "name": "Global Organic Textile Standard (GOTS) 7.0",
        "issuer_authority": "Global Standard gGmbH",
        "category": CertificateCategory.ENVIRONMENTAL,
        "description": "The worldwide leading textile processing standard for organic fibres."
    },
    {
        "name": "OEKO-TEX® Standard 100",
        "issuer_authority": "OEKO-TEX Association",
        "category": CertificateCategory.CHEMICAL_SAFETY,
        "description": "Labels for textiles tested for harmful substances."
    },
    {
        "name": "SA8000 Social Accountability",
        "issuer_authority": "Social Accountability International",
        "category": CertificateCategory.SOCIAL,
        "description": "Leading social certification standard for factories and organizations."
    },
    {
        "name": "ISO 14001:2015",
        "issuer_authority": "ISO",
        "category": CertificateCategory.ENVIRONMENTAL,
        "description": "Criteria for an environmental management system."
    }
]

STANDARD_MATERIALS = [
    {
        "name": "Cotton (Conventional)",
        "code": "CO-CONV",
        "co2": 4.6,
        "type": MaterialType.NATURAL,
        "desc": "Standard natural cotton fiber grown using conventional farming methods."
    },
    {
        "name": "Cotton (Organic)",
        "code": "CO-ORG",
        "co2": 0.9,
        "type": MaterialType.NATURAL,
        "desc": "Natural cotton fiber grown without toxic pesticides or synthetic fertilizers (GOTS/OCS)."
    },
    {
        "name": "Polyester (Virgin)",
        "code": "PES-VIR",
        "co2": 5.5,
        "type": MaterialType.SYNTHETIC,
        "desc": "Standard synthetic polyethylene terephthalate (PET) derived from fossil fuels."
    },
    {
        "name": "Polyester (Recycled rPET)",
        "code": "PES-REC",
        "co2": 1.4,
        "type": MaterialType.RECYCLED,
        "desc": "Synthetic fiber made from post-consumer plastic bottles or textile waste."
    },
    {
        "name": "Nylon 6.6",
        "code": "PA66",
        "co2": 8.0,
        "type": MaterialType.SYNTHETIC,
        "desc": "High-strength synthetic polyamide fiber known for durability and elasticity."
    },
    {
        "name": "Elastane (Spandex)",
        "code": "EL",
        "co2": 3.5,
        "type": MaterialType.SYNTHETIC,
        "desc": "Synthetic fiber known for its exceptional elasticity."
    },
    {
        "name": "Aluminium (Recycled)",
        "code": "AL-REC",
        "co2": 2.3,
        "type": MaterialType.METAL,
        "desc": "Recovered aluminium used for hardware, buttons, or zippers."
    }
]

# ==============================================================================
# 4. CONFIGURATION: TEMPLATES
# ==============================================================================
SYSTEM_TEMPLATE = {
    "name": "System Default - Clean",
    "description": "The standard minimalist layout provided by the platform.",
    "category": TemplateCategory.GENERIC,
    "version_label": "v1.0.0",
    "is_system_default": True,
    "layout_config": {
        "header": {"enabled": True, "sticky": True},
        "sections": ["hero", "specs", "traceability", "recycling"]
    },
    "style_config": {
        "primary_color": "#000000",
        "font_family": "Inter, sans-serif"
    },
    # Fields to generate for this template
    "fields": [
        {"key": "hero.headline", "type": TemplateFieldType.HEADER,
            "default": "Product Journey", "desc": "Main Page Title"},
        {"key": "specs.material_header", "type": TemplateFieldType.HEADER,
            "default": "Material Composition", "desc": "Header for materials"},
        {"key": "traceability.origin_label", "type": TemplateFieldType.LABEL,
            "default": "Country of Origin", "desc": "Label for origin country"},
        {"key": "recycling.cta", "type": TemplateFieldType.TEXT,
            "default": "How to Recycle", "desc": "Button text"},
    ]
}


# ==============================================================================
# SEED FUNCTIONS
# ==============================================================================

def seed_permissions(session: Session) -> dict[str, Permission]:
    """Creates system permissions."""
    logger.info("--- Seeding Permissions ---")
    perm_map = {}

    for key, desc in SYSTEM_PERMISSIONS.items():
        existing = session.exec(select(Permission).where(
            Permission.key == key)).first()
        if not existing:
            perm = Permission(key=key, description=desc)
            session.add(perm)
            session.flush()  # flush to generate ID
            existing = perm
            logger.info(f"Created Permission: {key}")
        perm_map[key] = existing

    return perm_map


def seed_roles(session: Session, perm_map: dict[str, Permission]):
    """Creates Global Roles and links permissions."""
    logger.info("--- Seeding Roles ---")

    for role_name, perm_keys in GLOBAL_ROLES.items():
        # Look for global role (tenant_id is None)
        role = session.exec(select(Role).where(
            Role.name == role_name, Role.tenant_id == None)).first()

        if not role:
            role = Role(name=role_name, tenant_id=None,
                        description=f"System Global Role: {role_name}")
            session.add(role)
            session.flush()
            logger.info(f"Created Role: {role_name}")

        # Sync Permissions
        current_links = session.exec(select(RolePermissionLink).where(
            RolePermissionLink.role_id == role.id)).all()
        existing_perm_ids = {link.permission_id for link in current_links}

        target_perm_ids = {perm_map[k].id for k in perm_keys if k in perm_map}

        for pid in target_perm_ids:
            if pid not in existing_perm_ids:
                session.add(RolePermissionLink(
                    role_id=role.id, permission_id=pid))
                logger.debug(f"  + Added perm ID {pid} to {role_name}")


def seed_certificates(session: Session):
    """Creates standard global certificate definitions."""
    logger.info("--- Seeding Certificates ---")
    for cert_data in STANDARD_CERTIFICATES:
        exists = session.exec(select(CertificateDefinition).where(
            CertificateDefinition.name == cert_data["name"],
            CertificateDefinition.tenant_id == None
        )).first()

        if not exists:
            cert = CertificateDefinition(
                tenant_id=None,  # Global
                **cert_data
            )
            session.add(cert)
            logger.info(f"Created Cert Definition: {cert_data['name']}")


def seed_materials(session: Session):
    """Creates standard global material definitions."""
    logger.info("--- Seeding Materials ---")
    for mat_data in STANDARD_MATERIALS:
        # Check existence by Code + Global Scope (tenant_id=None)
        exists = session.exec(select(MaterialDefinition).where(
            MaterialDefinition.code == mat_data["code"],
            MaterialDefinition.tenant_id == None
        )).first()

        if not exists:
            mat = MaterialDefinition(
                tenant_id=None,  # Global System Material
                name=mat_data["name"],
                code=mat_data["code"],
                default_carbon_footprint=mat_data["co2"],

                # NEW FIELDS MAPPED HERE
                material_type=mat_data["type"],
                description=mat_data["desc"]
            )
            session.add(mat)
            logger.info(f"Created Material: {mat_data['name']}")


def seed_system_template(session: Session):
    """Creates the default DPP Template and its translation fields."""
    logger.info("--- Seeding System Template ---")

    tpl_data = SYSTEM_TEMPLATE

    # 1. Create Template
    template = session.exec(select(DPPTemplate).where(
        DPPTemplate.name == tpl_data["name"],
        DPPTemplate.is_system_default == True
    )).first()

    if not template:
        template = DPPTemplate(
            name=tpl_data["name"],
            description=tpl_data["description"],
            category=tpl_data["category"],
            version_label=tpl_data["version_label"],
            is_system_default=True,
            tenant_id=None,  # Global
            layout_config=tpl_data["layout_config"],
            style_config=tpl_data["style_config"]
        )
        session.add(template)
        session.flush()
        logger.info(f"Created System Template: {template.name}")

    # 2. Create Fields
    existing_fields = session.exec(select(DPPTemplateField).where(
        DPPTemplateField.template_id == template.id)).all()
    existing_keys = {f.key for f in existing_fields}

    for field_data in tpl_data["fields"]:
        if field_data["key"] not in existing_keys:
            f_obj = DPPTemplateField(
                template_id=template.id,
                key=field_data["key"],
                field_type=field_data["type"],
                default_text=field_data["default"],
                description=field_data["desc"]
            )
            session.add(f_obj)
            logger.debug(f"  + Added field: {field_data['key']}")


def seed_system_admin(session: Session):
    """
    Optional: Creates the 'God Mode' Tenant and User to enable login.
    """
    logger.info("--- Seeding System Admin Tenant & User ---")

    # 1. Create System Tenant
    sys_tenant = session.exec(select(Tenant).where(
        Tenant.type == TenantType.SYSTEM_ADMIN)).first()
    if not sys_tenant:
        sys_tenant = Tenant(
            name="Platform Admin",
            slug="system-admin",
            type=TenantType.SYSTEM_ADMIN,
            status=TenantStatus.ACTIVE,
            location_country="US"
        )
        session.add(sys_tenant)
        session.flush()
        logger.info("Created System Tenant")

    # 2. Create System User (Password should be hashed in real app)
    # WARNING: Use a proper password hasher (like passlib) in production code!
    # Here we simulate a hashed string.
    sys_email = "admin@platform.com"
    sys_user = session.exec(select(User).where(
        User.email == sys_email)).first()
    if not sys_user:
        sys_user = User(
            email=sys_email,
            hashed_password="CHANGE_ME_HASH",
            first_name="System",
            last_name="Administrator",
            is_active=True
        )
        session.add(sys_user)
        session.flush()
        logger.info("Created System Admin User")

    # 3. Link them via Member
    # Find the "System Admin" Role we created earlier
    sys_role = session.exec(select(Role).where(
        Role.name == "System Admin", Role.tenant_id == None)).first()

    if sys_role:
        membership = session.exec(select(TenantMember).where(
            TenantMember.user_id == sys_user.id,
            TenantMember.tenant_id == sys_tenant.id
        )).first()

        if not membership:
            membership = TenantMember(
                user_id=sys_user.id,
                tenant_id=sys_tenant.id,
                role_id=sys_role.id,
                status=MemberStatus.ACTIVE
            )
            session.add(membership)
            logger.info("Linked Admin User to Admin Tenant")


# ==============================================================================
# MAIN EXECUTION
# ==============================================================================

def main():
    logger.info("Starting Database Seeding...")
    with Session(engine) as session:
        try:
            # 1. Access Control
            perm_map = seed_permissions(session)
            seed_roles(session, perm_map)

            # 2. Libraries / Master Data
            seed_certificates(session)
            seed_materials(session)

            # 3. UI Templates
            seed_system_template(session)

            # 4. Bootstrap User (Optional)
            seed_system_admin(session)

            session.commit()
            logger.info("Database seeding completed successfully.")

        except Exception as e:
            session.rollback()
            logger.error(f"Seeding failed: {e}")
            raise e


if __name__ == "__main__":
    main()
