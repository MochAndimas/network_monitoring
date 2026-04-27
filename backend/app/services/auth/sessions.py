"""Define module logic for `backend/app/services/auth/sessions.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.time import utcnow
from ...models.user import AuthLoginAttempt, AuthSession, User


async def list_active_sessions_for_user(db: AsyncSession, *, user_id: int, current_jwt_id: str | None) -> list[AuthSession]:
    """List active sessions for one user ordered by recency.

    Args:
        db: Parameter input untuk routine ini.
        user_id: Parameter input untuk routine ini.
        current_jwt_id: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    rows = await db.scalars(
        select(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        )
        .order_by(AuthSession.last_seen_at.desc(), AuthSession.created_at.desc())
    )
    sessions = list(rows.all())
    return sessions


async def revoke_other_sessions_for_user(db: AsyncSession, *, user_id: int, current_jwt_id: str | None) -> int:
    """Revoke all sessions except the current one for a user.

    Args:
        db: Parameter input untuk routine ini.
        user_id: Parameter input untuk routine ini.
        current_jwt_id: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    current_time = utcnow()
    result = await db.execute(
        select(AuthSession).where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > current_time,
        )
    )
    revoked = 0
    for session in result.scalars().all():
        if current_jwt_id and session.jwt_id == current_jwt_id:
            continue
        session.revoked_at = current_time
        revoked += 1
    await db.commit()
    return revoked


async def cleanup_auth_data(db: AsyncSession, *, commit: bool = True) -> dict[str, int]:
    """Delete expired session and login-attempt records by retention policy.

    Args:
        db: Parameter input untuk routine ini.
        commit: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    now = utcnow()
    session_cutoff = now - timedelta(days=settings.auth_session_retention_days)
    attempt_cutoff = now - timedelta(days=settings.auth_login_attempt_retention_days)

    deleted_sessions_result = await db.execute(
        delete(AuthSession).where(
            (AuthSession.expires_at < session_cutoff)
            | ((AuthSession.revoked_at.is_not(None)) & (AuthSession.revoked_at < session_cutoff))
        )
    )
    deleted_attempts_result = await db.execute(
        delete(AuthLoginAttempt).where(AuthLoginAttempt.attempted_at < attempt_cutoff)
    )
    if commit:
        await db.commit()
    else:
        await db.flush()
    return {
        "auth_sessions_deleted": int(getattr(deleted_sessions_result, "rowcount", 0) or 0),
        "auth_login_attempts_deleted": int(getattr(deleted_attempts_result, "rowcount", 0) or 0),
    }


async def list_sessions_for_admin(
    db: AsyncSession,
    *,
    username: str | None = None,
    include_revoked: bool = False,
) -> list[tuple[AuthSession, User]]:
    """List user sessions for admin management workflows.

    Args:
        db: Parameter input untuk routine ini.
        username: Parameter input untuk routine ini.
        include_revoked: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    query = (
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .order_by(AuthSession.last_seen_at.desc(), AuthSession.created_at.desc())
    )
    if username:
        query = query.where(User.username == username.strip().lower())
    if not include_revoked:
        query = query.where(AuthSession.revoked_at.is_(None), AuthSession.expires_at > utcnow())
    rows = await db.execute(query)
    return [(session, user) for session, user in rows.all()]


async def revoke_all_sessions_for_user(db: AsyncSession, *, user_id: int) -> int:
    """Revoke every active session for a user.

    Args:
        db: Parameter input untuk routine ini.
        user_id: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    current_time = utcnow()
    result = await db.execute(
        select(AuthSession).where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
    )
    revoked = 0
    for session in result.scalars().all():
        session.revoked_at = current_time
        revoked += 1
    await db.commit()
    return revoked
