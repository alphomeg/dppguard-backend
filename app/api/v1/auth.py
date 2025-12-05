from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger

from app.core.dependencies import get_user_service, get_current_user
from app.services.user import UserService
from app.db.schema import User
from app.models.auth import Token, TokenAccess, TokenRefresh
from app.models.user import UserSignin, UserRead, UserCreate


router = APIRouter()


@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    response_model=UserRead,
    summary="Register a new user",
    description="Creates a user and their personal workspace."
)
def signup(
    user_in: UserCreate,
    service: UserService = Depends(get_user_service)
):
    """
    1. Validates input (Pydantic).
    2. Calls Service to create User + Tenant + Membership (Atomic).
    3. Returns public user info.
    """
    try:
        new_user = service.create_user(user_in)
        return new_user
    except ValueError as e:
        logger.warning(f"Signup validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except Exception as e:
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
def token(
    signin_data: UserSignin,
    service: UserService = Depends(get_user_service)
):
    """
    1. Verifies password.
    2. Checks if user is Active.
    3. Issues JWTs.
    """
    # 1. Authenticate (Checks Email & Password)
    user = service.authenticate_user(signin_data.email, signin_data.password)

    if not user:
        # Security: Return generic error to prevent user enumeration
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
    description="Exchanges a valid Refresh Token for a new pair of Access/Refresh tokens."
)
def refresh_token(
    refresh_data: TokenRefresh,
    service: UserService = Depends(get_user_service)
):
    """
    1. Validates the signature of the refresh token.
    2. Ensures the token is actually a 'refresh' type (not an access token).
    3. Verifies the user still exists and is active.
    4. Returns a fresh pair of tokens.
    """
    return TokenAccess(access_token=service.refresh_session(refresh_data.refresh_token))


@router.get(
    "/",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    summary="Get current user",
    description="Returns the profile information of the currently authenticated user."
)
def get_me(
    current_user: User = Depends(get_current_user)
):
    """
    Protected route. 
    The 'current_user' argument is automatically populated by the 
    'get_current_user' dependency. If the token is invalid, this function
    is never actually called; FastAPI raises 401 before we get here.
    """
    return current_user
