from typing import Optional
import uuid
import secrets
from sqlmodel import Session, select
from loguru import logger
import jwt
from datetime import datetime, timedelta
from fastapi import HTTPException, status
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError

from app.core.config import settings
from app.db.schema import (
    User, Tenant, TenantMember, TenantType,
    TenantStatus, Role, MemberStatus
)
from app.models.auth import Token, TokenData
from app.models.user import UserCreate
from .password import get_password_hash, verify_password


class UserService:
    ALGORITHM = "HS256"

    def __init__(self, session: Session):
        self.session = session

    def _generate_personal_slug(self, first_name: str) -> str:
        """Generates a URL-safe slug: 'john-workspace-a1b2'."""
        safe_name = "".join(c for c in first_name.lower()
                            if c.isalnum()) or "user"
        suffix = secrets.token_hex(3)
        return f"{safe_name}-workspace-{suffix}"

    def _create_jwt(self, subject: str, expires_delta: timedelta, type: str) -> str:
        """Helper to sign JWTs with specific types."""
        to_encode = {
            "sub": str(subject),
            "exp": datetime.utcnow() + expires_delta,
            "type": type  # Access or Refresh
        }
        return jwt.encode(to_encode, settings.secret_key, algorithm=self.ALGORITHM)

    def get_user_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        """Retrieves a user by normalized email address."""
        statement = select(User).where(User.id == user_id)
        return self.session.exec(statement).first()

    def get_user_by_email(self, email: str) -> Optional[User]:
        """Retrieves a user by normalized email address."""
        statement = select(User).where(User.email == email)
        return self.session.exec(statement).first()

    def get_active_tenant_id(self, user: User) -> uuid.UUID:
        """
        Helper to resolve which Tenant the user is currently acting in.
        """
        active_membership = next(
            (m for m in user.memberships if m.status == MemberStatus.ACTIVE),
            None
        )

        if not active_membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not belong to any active workspace."
            )

        return active_membership.tenant_id

    def create_user(self, user_in: UserCreate) -> User:
        """
        Orchestrates the Registration Flow:
        1. Checks for duplicates.
        2. Hashes password.
        3. Creates User.
        4. Creates Personal Tenant.
        5. Links User to Tenant as Owner.
        6. Commits atomically.
        """

        # 1. Check existence
        if self.get_user_by_email(user_in.email):
            raise ValueError("An user with this email already exists.")

        # 2. Preparation
        hashed_pw = get_password_hash(user_in.password)

        owner_role = self.session.exec(
            select(Role).where(Role.name == "Owner", Role.tenant_id == None)
        ).first()

        if not owner_role:
            logger.critical(
                "System misconfiguration: Global 'Owner' role not found.")
            raise ValueError("System error: Default roles not initialized.")

        try:
            # 3. Create User Object
            new_user = User(
                email=user_in.email,
                hashed_password=hashed_pw,
                first_name=user_in.first_name,
                last_name=user_in.last_name,
                is_active=True
            )
            self.session.add(new_user)
            self.session.flush()

            # 4. Create Personal Tenant
            # Logic: Every user gets a "sandbox" where they are the admin.
            tenant_name = f"{user_in.first_name}'s Workspace"
            tenant_slug = self._generate_personal_slug(user_in.first_name)

            new_tenant = Tenant(
                name=tenant_name,
                slug=tenant_slug,
                type=TenantType.PERSONAL,
                status=TenantStatus.ACTIVE,
            )
            self.session.add(new_tenant)
            self.session.flush()

            # 5. Create Membership (Link User <-> Tenant)
            membership = TenantMember(
                user_id=new_user.id,
                tenant_id=new_tenant.id,
                role_id=owner_role.id,
                status=MemberStatus.ACTIVE
            )
            self.session.add(membership)

            # 6. Atomic Commit
            # If anything failed above (slug collision, DB constraint),
            # execution jumps to except, and nothing is saved.
            self.session.commit()

            # Refresh to load relationships/timestamps if needed
            self.session.refresh(new_user)

            logger.info(
                f"Registered user {new_user.id} and created tenant {new_tenant.id}")
            return new_user

        except Exception as e:
            self.session.rollback()
            logger.error(f"Registration failed for {user_in.email}: {str(e)}")
            raise e

    def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """
        1. Verify password hash.
        """
        user = self.get_user_by_email(email)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    def generate_access_token(self, user: User) -> str:
        """Generates an Access token for a user."""
        return self._create_jwt(
            subject=user.id,
            expires_delta=timedelta(
                minutes=settings.access_token_expire_minutes),
            type="access"
        )

    def generate_refresh_token(self, user: User) -> str:
        """Generates an Access token for a user."""
        return self._create_jwt(
            subject=user.id,
            expires_delta=timedelta(
                days=settings.refresh_token_expire_minutes),
            type="refresh"
        )

    def generate_tokens(self, user: User) -> Token:
        """Generates a pair of Access and Refresh tokens."""

        # 1. Access Token (Short Lived)
        access_token = self.generate_access_token(user)

        # 2. Refresh Token (Long Lived)
        refresh_token = self.generate_refresh_token(user)

        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer"
        )

    def verify_access_token(self, token: str) -> str:
        payload = jwt.decode(token, settings.secret_key,
                             algorithms=[self.ALGORITHM])
        user_id = payload.get("sub")
        token_type = payload.get("type")

        if not user_id:
            return None

        if not token_type:
            return None

        if not token_type == "access":
            return None

        return TokenData(user_id=user_id)

    def verify_refresh_token(self, token: str) -> str:
        payload = jwt.decode(token, settings.secret_key,
                             algorithms=[self.ALGORITHM])
        user_id = payload.get("sub")
        token_type = payload.get("type")

        if not user_id:
            return None

        if not token_type:
            return None

        if not token_type == "refresh":
            return None

        return TokenData(user_id=user_id)

    def validate_user(self, user_id):
        """Validates if a user exists and is active."""
        user = self.get_user_by_id(user_id)
        if not user or not user.is_active:
            return None
        return user

    def refresh_session(self, refresh_token: str) -> Token:
        """
        Validates the refresh token and issues a new pair.
        """
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

        try:
            # 1. Decode
            payload = self.verify_refresh_token(refresh_token)

            if not payload:
                raise credentials_exception
        except (InvalidTokenError, ValidationError):
            raise credentials_exception

        user = self.validate_user(payload.user_id)

        if not user:
            raise credentials_exception

        # 4. Issue New Access Token
        return self.generate_access_token(user)
