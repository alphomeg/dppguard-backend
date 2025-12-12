from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlmodel import Session
from pydantic import ValidationError

from app.db.core import get_session
from app.services.user import UserService
from app.db.schema import User

from app.services.references.material import MaterialService
from app.services.references.supplier import SupplierService
from app.services.references.certification import CertificationService

from app.services.product import ProductService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="signin")


def get_user_service(session: Session = Depends(get_session)) -> UserService:
    """Creates a UserService instance using the active DB session."""
    return UserService(session)


def get_material_service(session: Session = Depends(get_session)) -> MaterialService:
    return MaterialService(session=session)


def get_supplier_service(session: Session = Depends(get_session)) -> SupplierService:
    return SupplierService(session=session)


def get_certification_service(session: Session = Depends(get_session)) -> CertificationService:
    return CertificationService(session=session)


def get_product_service(session: Session = Depends(get_session)) -> ProductService:
    return ProductService(session=session)


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
