"""Define module logic for `backend/app/services/auth/observability.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.time import utcnow
from ...models.user import AuthLoginAttempt, AuthSession


async def build_auth_observability_summary(db: AsyncSession) -> dict[str, int]:
    """Build auth-domain observability summary statistics.

    Args:
        db: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    window_start = utcnow() - timedelta(minutes=settings.auth_login_rate_limit_window_minutes)
    now = utcnow()
    active_sessions = await db.scalar(
        select(func.count(AuthSession.id)).where(
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
    )
    login_failures_window = await db.scalar(
        select(func.count(AuthLoginAttempt.id)).where(
            AuthLoginAttempt.was_successful.is_(False),
            AuthLoginAttempt.was_rate_limited.is_(False),
            AuthLoginAttempt.attempted_at >= window_start,
        )
    )
    login_rate_limited_window = await db.scalar(
        select(func.count(AuthLoginAttempt.id)).where(
            AuthLoginAttempt.was_rate_limited.is_(True),
            AuthLoginAttempt.attempted_at >= window_start,
        )
    )
    revoked_sessions_window = await db.scalar(
        select(func.count(AuthSession.id)).where(
            AuthSession.revoked_at.is_not(None),
            AuthSession.revoked_at >= window_start,
        )
    )
    return {
        "active_sessions": int(active_sessions or 0),
        "login_failures_window": int(login_failures_window or 0),
        "login_rate_limited_window": int(login_rate_limited_window or 0),
        "revoked_sessions_window": int(revoked_sessions_window or 0),
    }

