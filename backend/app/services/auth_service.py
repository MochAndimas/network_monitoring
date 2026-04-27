"""Define module logic for `backend/app/services/auth_service.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

from .auth.admin import (
    change_password_for_user,
    create_user_for_admin,
    list_users_for_admin,
    reset_user_password_for_admin,
    update_user_for_admin,
)
from .auth.authentication import (
    actor_has_permission,
    authenticate_token,
    authenticate_user,
    authenticate_user_with_options,
    clear_failed_login_attempts,
    ensure_login_not_rate_limited,
    get_user_from_access_token,
    get_user_from_refresh_token,
    get_user_from_token,
    record_login_attempt,
    refresh_user_session,
    revoke_token,
)
from .auth.bootstrap import ensure_bootstrap_admin
from .auth.observability import build_auth_observability_summary
from .auth.sessions import (
    cleanup_auth_data,
    list_active_sessions_for_user,
    list_sessions_for_admin,
    revoke_all_sessions_for_user,
    revoke_other_sessions_for_user,
)
from .auth.types import AuthenticatedActor, SessionTokens

__all__ = [
    "AuthenticatedActor",
    "SessionTokens",
    "actor_has_permission",
    "authenticate_token",
    "authenticate_user",
    "authenticate_user_with_options",
    "build_auth_observability_summary",
    "change_password_for_user",
    "cleanup_auth_data",
    "clear_failed_login_attempts",
    "create_user_for_admin",
    "ensure_bootstrap_admin",
    "ensure_login_not_rate_limited",
    "get_user_from_access_token",
    "get_user_from_refresh_token",
    "get_user_from_token",
    "list_active_sessions_for_user",
    "list_sessions_for_admin",
    "list_users_for_admin",
    "record_login_attempt",
    "refresh_user_session",
    "reset_user_password_for_admin",
    "revoke_all_sessions_for_user",
    "revoke_other_sessions_for_user",
    "revoke_token",
    "update_user_for_admin",
]

