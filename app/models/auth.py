from uuid import UUID
from sqlmodel import SQLModel


class Token(SQLModel):
    access_token: str
    refresh_token: str
    token_type: str


class TokenAccess(SQLModel):
    access_token: str


class TokenRefresh(SQLModel):
    refresh_token: str


class TokenData(SQLModel):
    user_id: UUID
