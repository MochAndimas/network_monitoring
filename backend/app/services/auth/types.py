"""Define module logic for `backend/app/services/auth/types.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ...models.user import AuthSession, User


@dataclass(slots=True)
class AuthenticatedActor:
    """Represent an authenticated caller resolved from token or API key context.

    Attributes:
        kind: Actor source category (for example ``user`` or ``api_key``).
        role: Effective role used by authorization checks.
        user: Associated persisted user, when the actor is user-backed.
        session: Associated auth session, when available.
        permissions: Fine-grained permissions/scopes granted to the actor.
        api_key_name: Friendly identifier for API-key actors.
    """

    kind: str
    role: str
    user: User | None = None
    session: AuthSession | None = None
    permissions: frozenset[str] = frozenset()
    api_key_name: str | None = None


@dataclass(slots=True)
class SessionTokens:
    """Bundle access/refresh JWT material returned after auth flows.

    Attributes:
        access_token: Signed short-lived token used for API access.
        refresh_token: Signed long-lived token used to renew sessions.
        access_expires_at: Expiration timestamp for the access token.
        refresh_expires_at: Expiration timestamp for the refresh token.
    """

    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime

