from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger

from app.core.dependencies import get_user_service, get_current_user
from app.services.user import UserService
from app.db.schema import User
from app.models.auth import Token, TokenAccess, TokenRefresh
from app.models.user import UserSignin, UserRead, ActiveTenantRead, UserCreate


router = APIRouter()


@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    response_model=UserRead,
    summary="Register a new Organization and User",
    description=(
        "Creates a new User, generates a unique Company/Tenant based on the "
        "'company_name' and 'account_type' (Brand/Supplier/Hybrid), and assigns "
        "the user as the Owner."
    )
)
def signup(
    user_in: UserCreate,
    service: UserService = Depends(get_user_service)
):
    """
    1. Validates input (Pydantic).
    2. Checks for Email and Company Name uniqueness.
    3. Creates User + Tenant + Owner Membership (Atomic Transaction).
    4. Returns public user info.
    """
    try:
        new_user = service.create_user(user_in)
        return new_user

    except ValueError as e:
        # Catch logic errors like "Email exists" or "Company name exists"
        logger.warning(f"Signup validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except Exception as e:
        # Catch unexpected DB or System errors
        logger.exception("Unexpected error during signup")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing your request."
        )


@router.post(
    "/token",
    response_model=Token,
    status_code=status.HTTP_200_OK,
    summary="Signin to get tokens",
    description="Returns an Access Token (short-lived) and Refresh Token (long-lived)."
)
def login(
    signin_data: UserSignin,
    service: UserService = Depends(get_user_service)
):
    """
    1. Verifies password.
    2. Checks if user is Active.
    3. Issues JWTs.
    """
    # 1. Authenticate (Checks Email & Password hash)
    user = service.authenticate_user(signin_data.email, signin_data.password)

    if not user:
        # Security: Generic error to prevent user enumeration
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. Check Active Status
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Please contact support."
        )

    # 3. Generate JWT Tokens
    tokens = service.generate_tokens(user)

    logger.info(f"User logged in: {user.id}")

    return tokens


@router.post(
    "/refresh",
    response_model=TokenAccess,
    status_code=status.HTTP_200_OK,
    summary="Refresh Session",
    description="Exchanges a valid Refresh Token for a new Access Token."
)
def refresh_token(
    refresh_data: TokenRefresh,
    service: UserService = Depends(get_user_service)
):
    """
    1. Validates the signature of the refresh token.
    2. Ensures the token is actually a 'refresh' type.
    3. Verifies the user still exists and is active.
    4. Returns a fresh Access token.
    """
    # The service handles all validation logic and raises 401 if invalid
    new_access_token = service.refresh_session(refresh_data.refresh_token)

    return TokenAccess(access_token=new_access_token)


@router.get(
    "/me",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    summary="Get current user",
    description="Returns profile info + details of the active tenant context."
)
def get_me(
    current_user: User = Depends(get_current_user)
):
    # 1. Retrieve the tenant ID injected by the dependency
    active_tenant_id = getattr(current_user, "_tenant_id", None)

    active_tenant_data = None

    # 2. Find the actual Tenant object
    # We iterate through the user's memberships to find the one matching the active ID.
    # Note: This relies on 'current_user.memberships' being loaded.
    # If using SQLModel/SQLAlchemy lazy loading, accessing this might trigger a DB query, which is fine.
    if active_tenant_id:
        for member in current_user.memberships:
            if member.tenant_id == active_tenant_id:
                # We found the active tenant object
                tenant_obj = member.tenant

                active_tenant_data = ActiveTenantRead(
                    id=tenant_obj.id,
                    name=tenant_obj.name,
                    slug=tenant_obj.slug,
                    type=tenant_obj.type,
                    location_country=getattr(
                        tenant_obj, 'location_country', None)
                )
                break

    # 3. Construct and return the response model
    return UserRead(
        id=current_user.id,
        email=current_user.email,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        is_active=current_user.is_active,
        current_tenant=active_tenant_data
    )
