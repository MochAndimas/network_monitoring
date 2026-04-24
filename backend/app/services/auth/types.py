"""Auth service shared dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ...models.user import AuthSession, User


@dataclass(slots=True)
class AuthenticatedActor:
    kind: str
    role: str
    user: User | None = None
    session: AuthSession | None = None
    permissions: frozenset[str] = frozenset()
    api_key_name: str | None = None


@dataclass(slots=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime

