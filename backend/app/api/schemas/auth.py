"""Provide API response and request schemas for the network monitoring project."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    """Represent login request behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=255)
    remember: bool = False


class UserSessionInfo(BaseModel):
    """Represent user session info behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    id: int
    username: str
    full_name: str
    role: str
    expires_at: datetime


class LoginResponse(BaseModel):
    """Represent login response behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    access_token: str
    token_type: str = "Bearer"
    user: UserSessionInfo


class CurrentUserResponse(BaseModel):
    """Represent current user response behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    id: int
    username: str
    full_name: str
    role: str
    auth_kind: str = "user"
    scopes: list[str] = []
    expires_at: datetime | None = None


class AuthSessionItem(BaseModel):
    """Represent auth session item behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    session_id: int
    client_ip: str
    user_agent: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    is_current: bool


class LogoutAllResponse(BaseModel):
    """Represent logout all response behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    success: bool = True
    revoked_sessions: int


class AuthAdminSessionItem(BaseModel):
    """Represent auth admin session item behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
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
    """Represent user admin item behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
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
    """Represent user admin create request behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    username: str = Field(min_length=3, max_length=100)
    full_name: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=255)
    role: str = Field(default="viewer", pattern="^(admin|viewer)$")


class UserAdminUpdateRequest(BaseModel):
    """Represent user admin update request behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    role: str | None = Field(default=None, pattern="^(admin|viewer)$")
    is_active: bool | None = None
    disabled_reason: str | None = Field(default=None, max_length=255)


class UserPasswordResetRequest(BaseModel):
    """Represent user password reset request behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    new_password: str = Field(min_length=1, max_length=255)


class ChangePasswordRequest(BaseModel):
    """Represent change password request behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    current_password: str = Field(min_length=1, max_length=255)
    new_password: str = Field(min_length=1, max_length=255)


class AdminAuditLogItem(BaseModel):
    """Represent admin audit log item behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
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
