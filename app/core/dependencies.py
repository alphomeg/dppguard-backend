from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlmodel import Session
from pydantic import ValidationError

from app.db.core import get_session

from app.services.user import UserService
from app.db.schema import User

from app.services.material_definition import MaterialDefinitionService

from app.services.certificate_definition import CertificateDefinitionService

from app.services.supplier_profile import SupplierProfileService

from app.services.supplier_dashboard import SupplierDashboardService

from app.services.tenant_connection import TenantConnectionService

from app.services.product import ProductService

from app.services.product_contribution import ProductContributionService

# from app.services.collaboration import CollaborationService

# from app.services.brand import BrandService


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="signin")


def get_user_service(session: Session = Depends(get_session)) -> UserService:
    """Creates a UserService instance using the active DB session."""
    return UserService(session)


def get_material_definition_service(session: Session = Depends(get_session)) -> MaterialDefinitionService:
    """Creates a MaterialDefinitionService instance using the active DB session."""
    return MaterialDefinitionService(session)


def get_certificate_definition_service(session: Session = Depends(get_session)) -> CertificateDefinitionService:
    return CertificateDefinitionService(session)


def get_product_service(session=Depends(get_session)) -> ProductService:
    return ProductService(session)


def get_product_contribution_service(session=Depends(get_session)) -> ProductContributionService:
    return ProductContributionService(session)


# def get_brand_service(session: Session = Depends(get_session)) -> BrandService:
#     return BrandService(session)


# def get_collab_service(session: Session = Depends(get_session)) -> CollaborationService:
#     return CollaborationService(session)


def get_supplier_service(session: Session = Depends(get_session)) -> SupplierProfileService:
    """Dependency injection for SupplierProfileService."""
    return SupplierProfileService(session)


def get_supplier_dashboard_service(session: Session = Depends(get_session)) -> SupplierDashboardService:
    """Dependency injection for SupplierDashboardService."""
    return SupplierDashboardService(session)


def get_tenant_connection_service(session=Depends(get_session)) -> TenantConnectionService:
    """Dependency injection for TenantConnectionService."""
    return TenantConnectionService(session)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    service: UserService = Depends(get_user_service)
) -> User:
    """
    Validates the JWT token and retrieves the user.
    This is the gatekeeper for protected routes.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        # 1. Verify the Token
        token_data = service.verify_access_token(token)

        if not token_data:
            raise credentials_exception

    except (InvalidTokenError, ValidationError):
        raise credentials_exception

    user = service.get_user_by_id(token_data.user_id)

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    user._tenant_id = service.get_active_tenant_id(user)

    return user
