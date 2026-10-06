"""Service-layer workflows for sessions."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.time import utcnow
from ...models.user import AuthLoginAttempt, AuthSession, User
from ..retention_batches import delete_rows_in_batches


async def list_active_sessions_for_user(
    db: AsyncSession, *, user_id: int, current_jwt_id: str | None
) -> list[AuthSession]:
    """List active sessions for user in the service layer."""
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


async def revoke_other_sessions_for_user(
    db: AsyncSession,
    *,
    user_id: int,
    current_jwt_id: str | None,
    commit: bool = True,
) -> int:
    """Revoke active user sessions while preserving the caller's current session."""
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
    if commit:
        await db.commit()
    else:
        await db.flush()
    return revoked


async def cleanup_auth_data(db: AsyncSession, *, commit: bool = True) -> dict[str, int]:
    """Clean up auth data in the service layer."""
    now = utcnow()
    auth_settings = settings.auth
    session_cutoff = now - timedelta(days=auth_settings.session_retention_days)
    attempt_cutoff = now - timedelta(days=auth_settings.login_attempt_retention_days)

    deleted_sessions = await delete_rows_in_batches(
        db,
        AuthSession,
        (AuthSession.expires_at < session_cutoff)
        | ((AuthSession.revoked_at.is_not(None)) & (AuthSession.revoked_at < session_cutoff)),
        commit=commit,
    )
    deleted_attempts = await delete_rows_in_batches(
        db, AuthLoginAttempt, AuthLoginAttempt.attempted_at < attempt_cutoff, commit=commit
    )
    return {"auth_sessions_deleted": deleted_sessions, "auth_login_attempts_deleted": deleted_attempts}


async def list_sessions_for_admin(
    db: AsyncSession,
    *,
    username: str | None = None,
    include_revoked: bool = False,
) -> list[tuple[AuthSession, User]]:
    """List sessions for admin in the service layer."""
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


async def revoke_all_sessions_for_user(db: AsyncSession, *, user_id: int, commit: bool = True) -> int:
    """Revoke every active session for a user."""
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
    if commit:
        await db.commit()
    else:
        await db.flush()
    return revoked
