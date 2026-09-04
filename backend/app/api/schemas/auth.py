"""Pydantic schemas for authentication and session management."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    """Pydantic schema for LoginRequest payloads."""
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=255)
    remember: bool = False


class UserSessionInfo(BaseModel):
    """Pydantic schema for UserSessionInfo payloads."""
    id: int
    username: str
    full_name: str
    role: str
    expires_at: datetime
    session_expires_at: datetime


class LoginResponse(BaseModel):
    """Pydantic schema for LoginResponse payloads."""
    access_token: str
    token_type: str = "Bearer"
    user: UserSessionInfo


class CurrentUserResponse(BaseModel):
    """Pydantic schema for CurrentUserResponse payloads."""
    id: int
    username: str
    full_name: str
    role: str
    auth_kind: str = "user"
    scopes: list[str] = []
    expires_at: datetime | None = None


class AuthSessionItem(BaseModel):
    """Pydantic schema for AuthSessionItem payloads."""
    session_id: int
    client_ip: str
    user_agent: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    is_current: bool


class LogoutAllResponse(BaseModel):
    """Pydantic schema for LogoutAllResponse payloads."""
    success: bool = True
    revoked_sessions: int


class AuthAdminSessionItem(BaseModel):
    """Pydantic schema for AuthAdminSessionItem payloads."""
    session_id: int
    user_id: int
    username: str
    full_name: str
    role: str
    client_ip: str
    user_agent: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    is_current: bool = False


class UserAdminItem(BaseModel):
    """Pydantic schema for UserAdminItem payloads."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    password_changed_at: datetime | None = None
    disabled_at: datetime | None = None
    disabled_reason: str | None = None


class UserAdminCreateRequest(BaseModel):
    """Pydantic schema for UserAdminCreateRequest payloads."""
    username: str = Field(min_length=3, max_length=100)
    full_name: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=255)
    role: str = Field(default="viewer", pattern="^(admin|viewer)$")


class UserAdminUpdateRequest(BaseModel):
    """Pydantic schema for UserAdminUpdateRequest payloads."""
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    role: str | None = Field(default=None, pattern="^(admin|viewer)$")
    is_active: bool | None = None
    disabled_reason: str | None = Field(default=None, max_length=255)


class UserPasswordResetRequest(BaseModel):
    """Pydantic schema for UserPasswordResetRequest payloads."""
    new_password: str = Field(min_length=1, max_length=255)


class ChangePasswordRequest(BaseModel):
    """Pydantic schema for ChangePasswordRequest payloads."""
    current_password: str = Field(min_length=1, max_length=255)
    new_password: str = Field(min_length=1, max_length=255)


class UpdateMyAccountRequest(BaseModel):
    """Request payload for a user updating their own profile."""

    full_name: str = Field(min_length=1, max_length=150)


class AdminAuditLogItem(BaseModel):
    """Pydantic schema for AdminAuditLogItem payloads."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_kind: str
    actor_id: int | None = None
    actor_username: str | None = None
    actor_role: str
    actor_api_key_name: str | None = None
    action: str
    target_type: str
    target_id: str | None = None
    ip_address: str
    user_agent: str
    details_json: str
    created_at: datetime
