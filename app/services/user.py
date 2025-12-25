from typing import Optional
import uuid
import re
import secrets
from datetime import datetime, timedelta

import jwt
from jwt.exceptions import InvalidTokenError
from loguru import logger
from sqlmodel import Session, select
from fastapi import HTTPException, status
from pydantic import ValidationError

from app.core.config import settings
from app.db.schema import (
    User, Tenant, TenantMember, TenantType,
    TenantStatus, Role, MemberStatus, TenantConnection, ConnectionStatus
)
from app.models.auth import Token, TokenData
from app.models.user import UserCreate
from .password import get_password_hash, verify_password


class UserService:
    ALGORITHM = "HS256"

    def __init__(self, session: Session):
        self.session = session

    def _generate_slug(self, name: str) -> str:
        """
        Generates a URL-safe slug from the company name.
        Example: 'Acme Clothing Co.' -> 'acme-clothing-co'
        """
        # 1. Lowercase and replace non-alphanumerics with hyphens
        slug = name.lower()
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        slug = slug.strip('-')

        # 2. Fallback if name was entirely symbols
        if not slug:
            slug = "org-" + secrets.token_hex(4)

        return slug

    def _ensure_slug_unique(self, base_slug: str) -> str:
        """
        Ensures the slug is unique in the database.
        If 'acme' exists, tries 'acme-1', 'acme-2', etc.
        """
        slug = base_slug
        counter = 1

        while True:
            # Check DB for existence
            statement = select(Tenant).where(Tenant.slug == slug)
            existing = self.session.exec(statement).first()

            if not existing:
                return slug

            # If exists, append counter and retry
            slug = f"{base_slug}-{counter}"
            counter += 1

            # Safety break to prevent infinite loops in weird edge cases
            if counter > 100:
                raise ValueError(
                    f"Could not generate a unique handle for company '{base_slug}'.")

    def _create_jwt(self, subject: str, expires_delta: timedelta, type: str) -> str:
        """Helper to sign JWTs with specific types."""
        to_encode = {
            "sub": str(subject),
            "exp": datetime.utcnow() + expires_delta,
            "type": type
        }
        return jwt.encode(to_encode, settings.secret_key, algorithm=self.ALGORITHM)

    def get_user_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        statement = select(User).where(User.id == user_id)
        return self.session.exec(statement).first()

    def get_user_by_email(self, email: str) -> Optional[User]:
        statement = select(User).where(User.email == email)
        return self.session.exec(statement).first()

    def get_active_tenant_id(self, user: User) -> uuid.UUID:
        """
        Resolves which Tenant the user is currently acting in.
        Strict Mode: The user MUST have an 'active' membership.
        """
        # 1. Filter for active memberships only
        active_membership = next(
            (m for m in user.memberships if m.status == MemberStatus.ACTIVE),
            None
        )

        # 2. If no active membership exists, deny access.
        # We do NOT fallback to index 0, as that could be an invited/pending
        # state or a suspended workspace which should not be accessed.
        if not active_membership:
            logger.warning(
                f"Access denied: User {user.id} has no active tenant membership.")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is not currently active in any workspace."
            )

        return active_membership.tenant_id

    def create_user(self, user_in: UserCreate) -> User:
        """
        Orchestrates Registration + Invitation Linking.
        """
        # 1. Check User Existence
        if self.get_user_by_email(user_in.email):
            raise ValueError("A user with this email already exists.")

        # 2. Check Organization Name
        existing_tenant = self.session.exec(
            select(Tenant).where(Tenant.name == user_in.company_name)
        ).first()
        if existing_tenant:
            raise ValueError(
                "An organization with this company name already exists.")

        # 3. Prepare Data
        hashed_pw = get_password_hash(user_in.password)
        owner_role = self.session.exec(
            select(Role).where(Role.name == "Owner", Role.tenant_id == None)
        ).first()

        if not owner_role:
            raise ValueError("System configuration error: Owner role missing.")

        try:
            # --- START ATOMIC TRANSACTION ---

            # A. Create User
            new_user = User(
                email=user_in.email,
                hashed_password=hashed_pw,
                first_name=user_in.first_name,
                last_name=user_in.last_name,
                is_active=True
            )
            self.session.add(new_user)
            self.session.flush()

            # B. Create Tenant
            base_slug = self._generate_slug(user_in.company_name)
            final_slug = self._ensure_slug_unique(base_slug)

            new_tenant = Tenant(
                name=user_in.company_name,
                slug=final_slug,
                type=user_in.account_type,
                status=TenantStatus.ACTIVE,
                location_country=user_in.location_country
            )
            self.session.add(new_tenant)
            self.session.flush()  # Need ID for linking

            # C. Create Owner Membership
            membership = TenantMember(
                user_id=new_user.id,
                tenant_id=new_tenant.id,
                role_id=owner_role.id,
                status=MemberStatus.ACTIVE
            )
            self.session.add(membership)

            # D. LINK PENDING INVITATIONS (The Logic You Requested)
            # Find any connection requests where the invite email matches this new user
            pending_invites = self.session.exec(
                select(TenantConnection)
                .where(TenantConnection.supplier_email_invite == user_in.email)
                .where(TenantConnection.status == ConnectionStatus.PENDING)
            ).all()

            for invite in pending_invites:
                # We link the real tenant ID now.
                invite.supplier_tenant_id = new_tenant.id
                # We do NOT set status to CONNECTED yet.
                # We keep it PENDING so the Supplier can explicitly "Accept" later.
                self.session.add(invite)
                logger.info(
                    f"Linked new Tenant {new_tenant.id} to Pending Invite {invite.id}")

            # --- COMMIT ---
            self.session.commit()
            self.session.refresh(new_user)

            logger.info(f"Registration successful for {new_user.email}")
            return new_user

        except Exception as e:
            self.session.rollback()
            logger.error(f"Registration failed: {str(e)}")
            raise e

    def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """Verify email and password hash."""
        user = self.get_user_by_email(email)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    def generate_access_token(self, user: User) -> str:
        return self._create_jwt(
            subject=user.id,
            expires_delta=timedelta(
                minutes=settings.access_token_expire_minutes),
            type="access"
        )

    def generate_refresh_token(self, user: User) -> str:
        return self._create_jwt(
            subject=user.id,
            expires_delta=timedelta(
                minutes=settings.refresh_token_expire_minutes),
            type="refresh"
        )

    def generate_tokens(self, user: User) -> Token:
        return Token(
            access_token=self.generate_access_token(user),
            refresh_token=self.generate_refresh_token(user),
            token_type="bearer"
        )

    def verify_access_token(self, token: str) -> Optional[TokenData]:
        try:
            payload = jwt.decode(token, settings.secret_key,
                                 algorithms=[self.ALGORITHM])
            user_id = payload.get("sub")
            token_type = payload.get("type")

            if not user_id or token_type != "access":
                return None

            return TokenData(user_id=uuid.UUID(user_id))
        except (jwt.PyJWTError, ValueError):
            return None

    def verify_refresh_token(self, token: str) -> Optional[TokenData]:
        try:
            payload = jwt.decode(token, settings.secret_key,
                                 algorithms=[self.ALGORITHM])
            user_id = payload.get("sub")
            token_type = payload.get("type")

            if not user_id or token_type != "refresh":
                return None

            return TokenData(user_id=uuid.UUID(user_id))
        except (jwt.PyJWTError, ValueError):
            return None

    def validate_user(self, user_id: uuid.UUID) -> Optional[User]:
        """Retrieves user and checks is_active flag."""
        user = self.get_user_by_id(user_id)
        if not user or not user.is_active:
            return None
        return user

    def refresh_session(self, refresh_token: str) -> str:
        """
        Exchange a valid refresh token for a new access token.
        Strictly validates the user state before issuing.
        """
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

        # 1. Verify Token Signature & Type
        token_data = self.verify_refresh_token(refresh_token)
        if not token_data:
            raise credentials_exception

        # 2. Verify User Exists & Is Active
        user = self.validate_user(token_data.user_id)
        if not user:
            raise credentials_exception

        # 3. Issue New Access Token
        return self.generate_access_token(user)
