"""Provide business services that coordinate repositories and domain workflows for the network monitoring project."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.security import (
    JWTValidationError,
    TokenPayload,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    generate_session_jwt_id,
    hash_password,
    hash_session_token,
    session_expiry,
    validate_password_strength,
    verify_password,
)
from ..core.time import utcnow
from ..models.user import AuthLoginAttempt, AuthSession, User


@dataclass(slots=True)
class AuthenticatedActor:
    """Represent authenticated actor behavior and data for business services that coordinate repositories and domain workflows.
    """
    kind: str
    role: str
    user: User | None = None
    session: AuthSession | None = None
    permissions: frozenset[str] = frozenset()
    api_key_name: str | None = None


@dataclass(slots=True)
class SessionTokens:
    """Represent session tokens behavior and data for business services that coordinate repositories and domain workflows.
    """
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


async def ensure_bootstrap_admin(db: AsyncSession) -> bool:
    """Ensure bootstrap admin for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).

    Returns:
        `bool` result produced by the routine.
    """
    if not settings.bootstrap_admin_password:
        return False

    username = settings.bootstrap_admin_username.strip().lower()
    existing = await db.scalar(select(User).where(User.username == username))
    if existing is not None:
        return False

    user = User(
        username=username,
        full_name=settings.bootstrap_admin_full_name.strip() or "Monitoring Admin",
        password_hash=hash_password(settings.bootstrap_admin_password),
        role="admin",
        is_active=True,
        password_changed_at=utcnow(),
    )
    db.add(user)
    await db.commit()
    return True


async def authenticate_user(db: AsyncSession, username: str, password: str) -> tuple[User, str, datetime]:
    """Handle authenticate user for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        username: username value used by this routine (type `str`).
        password: password value used by this routine (type `str`).

    Returns:
        `tuple[User, str, datetime]` result produced by the routine.
    """
    user, tokens = await authenticate_user_with_options(db, username, password, remember=False)
    return user, tokens.access_token, tokens.access_expires_at


async def authenticate_user_with_options(
    db: AsyncSession,
    username: str,
    password: str,
    *,
    remember: bool,
    client_ip: str = "",
    user_agent: str = "",
) -> tuple[User, SessionTokens]:
    """Handle authenticate user with options for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        username: username value used by this routine (type `str`).
        password: password value used by this routine (type `str`).
        remember: remember keyword value used by this routine (type `bool`).
        client_ip: client ip keyword value used by this routine (type `str`, optional).
        user_agent: user agent keyword value used by this routine (type `str`, optional).

    Returns:
        `tuple[User, SessionTokens]` result produced by the routine.
    """
    normalized_username = username.strip().lower()
    await ensure_login_not_rate_limited(db, username=normalized_username, client_ip=client_ip)
    user = await db.scalar(select(User).where(User.username == normalized_username))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        await record_login_attempt(db, username=normalized_username, client_ip=client_ip, was_successful=False)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    session_jti = generate_session_jwt_id()
    refresh_nonce = generate_session_jwt_id()
    refresh_expires_at = session_expiry(
        settings.auth_remember_ttl_minutes if remember else settings.auth_token_ttl_minutes
    )
    access_expires_at = min(session_expiry(settings.auth_token_ttl_minutes), refresh_expires_at)
    db.add(
        AuthSession(
            user_id=user.id,
            jwt_id=session_jti,
            token_hash=hash_session_token(refresh_nonce),
            client_ip=client_ip,
            user_agent=(user_agent or "")[:255],
            expires_at=refresh_expires_at,
            last_seen_at=utcnow(),
        )
    )
    await clear_failed_login_attempts(db, username=normalized_username, client_ip=client_ip)
    await db.commit()
    return user, _build_session_tokens(user, session_jti=session_jti, refresh_nonce=refresh_nonce, refresh_expires_at=refresh_expires_at, access_expires_at=access_expires_at)


async def authenticate_token(db: AsyncSession, token: str) -> tuple[User, AuthSession]:
    """Handle authenticate token for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        token: token value used by this routine (type `str`).

    Returns:
        `tuple[User, AuthSession]` result produced by the routine.
    """
    actor = await get_user_from_access_token(db, token)
    if actor.user is None or actor.session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return actor.user, actor.session


async def refresh_user_session(db: AsyncSession, refresh_token: str) -> tuple[User, SessionTokens]:
    """Refresh user session for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        refresh_token: refresh token value used by this routine (type `str`).

    Returns:
        `tuple[User, SessionTokens]` result produced by the routine.
    """
    actor, payload = await _authenticate_session_for_refresh(db, refresh_token)
    if actor.user is None or actor.session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    session_jti = actor.session.jwt_id or payload.jwt_id or generate_session_jwt_id()
    new_refresh_nonce = generate_session_jwt_id()
    actor.session.jwt_id = session_jti
    actor.session.token_hash = hash_session_token(new_refresh_nonce)
    actor.session.last_seen_at = utcnow()
    refresh_expires_at = actor.session.expires_at
    access_expires_at = min(session_expiry(settings.auth_token_ttl_minutes), refresh_expires_at)
    await db.commit()
    tokens = _build_session_tokens(
        actor.user,
        session_jti=session_jti,
        refresh_nonce=new_refresh_nonce,
        refresh_expires_at=refresh_expires_at,
        access_expires_at=access_expires_at,
    )
    return actor.user, tokens


def actor_has_permission(actor: AuthenticatedActor, permission: str) -> bool:
    """Handle actor has permission for business services that coordinate repositories and domain workflows.

    Args:
        actor: actor value used by this routine (type `AuthenticatedActor`).
        permission: permission value used by this routine (type `str`).

    Returns:
        `bool` result produced by the routine.
    """
    if actor.user is not None:
        return actor.role == "admin"
    return permission in actor.permissions


async def get_user_from_access_token(db: AsyncSession, token: str) -> AuthenticatedActor:
    """Return user from access token for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        token: token value used by this routine (type `str`).

    Returns:
        `AuthenticatedActor` result produced by the routine.
    """
    try:
        payload = decode_access_token(token)
    except JWTValidationError:
        return await _get_user_from_legacy_token(db, token)
    if payload.token_type != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    session = await _get_active_session_by_jwt_id(db, payload.jwt_id)
    user = await _get_active_user_for_session(db, session, subject=payload.subject)
    return AuthenticatedActor(kind="user", role=user.role, user=user, session=session)


async def get_user_from_refresh_token(db: AsyncSession, token: str) -> AuthenticatedActor:
    """Return user from refresh token for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        token: token value used by this routine (type `str`).

    Returns:
        `AuthenticatedActor` result produced by the routine.
    """
    try:
        actor, _payload = await _authenticate_refresh_token(db, token)
    except JWTValidationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc
    return actor


async def get_user_from_token(db: AsyncSession, token: str) -> AuthenticatedActor:
    """Return user from token for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        token: token value used by this routine (type `str`).

    Returns:
        `AuthenticatedActor` result produced by the routine.
    """
    try:
        payload = decode_access_token(token)
    except JWTValidationError:
        return await _get_user_from_legacy_token(db, token)
    if payload.token_type == "refresh":
        return await get_user_from_refresh_token(db, token)
    return await get_user_from_access_token(db, token)


async def revoke_token(db: AsyncSession, token: str) -> None:
    """Handle revoke token for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        token: token value used by this routine (type `str`).

    Returns:
        None. The routine is executed for its side effects.
    """
    session = None
    try:
        payload = decode_access_token(token)
    except JWTValidationError:
        token_hash = hash_session_token(token)
        session = await db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
    else:
        session = await db.scalar(select(AuthSession).where(AuthSession.jwt_id == payload.jwt_id))
    if session is None:
        return
    session.revoked_at = utcnow()
    await db.commit()


async def list_active_sessions_for_user(db: AsyncSession, *, user_id: int, current_jwt_id: str | None) -> list[AuthSession]:
    """Return a list of active sessions for user for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        user_id: user id keyword value used by this routine (type `int`).
        current_jwt_id: current jwt id keyword value used by this routine (type `str | None`).

    Returns:
        `list[AuthSession]` result produced by the routine.
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
    """Handle revoke other sessions for user for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        user_id: user id keyword value used by this routine (type `int`).
        current_jwt_id: current jwt id keyword value used by this routine (type `str | None`).

    Returns:
        `int` result produced by the routine.
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


async def ensure_login_not_rate_limited(db: AsyncSession, *, username: str, client_ip: str) -> None:
    """Ensure login not rate limited for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        username: username keyword value used by this routine (type `str`).
        client_ip: client ip keyword value used by this routine (type `str`).

    Returns:
        None. The routine is executed for its side effects.
    """
    window_start = utcnow() - timedelta(minutes=settings.auth_login_rate_limit_window_minutes)
    failed_attempts = await db.scalar(
        select(func.count(AuthLoginAttempt.id)).where(
            AuthLoginAttempt.username == username,
            AuthLoginAttempt.client_ip == client_ip,
            AuthLoginAttempt.was_successful.is_(False),
            AuthLoginAttempt.attempted_at >= window_start,
        )
    )
    if int(failed_attempts or 0) >= settings.auth_login_rate_limit_max_attempts:
        await record_login_attempt(db, username=username, client_ip=client_ip, was_successful=False, was_rate_limited=True)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
        )


async def record_login_attempt(
    db: AsyncSession,
    *,
    username: str,
    client_ip: str,
    was_successful: bool,
    was_rate_limited: bool = False,
) -> None:
    """Record login attempt for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        username: username keyword value used by this routine (type `str`).
        client_ip: client ip keyword value used by this routine (type `str`).
        was_successful: was successful keyword value used by this routine (type `bool`).
        was_rate_limited: was rate limited keyword value used by this routine (type `bool`, optional).

    Returns:
        None. The routine is executed for its side effects.
    """
    db.add(
        AuthLoginAttempt(
            username=username,
            client_ip=client_ip,
            was_successful=was_successful,
            was_rate_limited=was_rate_limited,
            attempted_at=utcnow(),
        )
    )
    await db.commit()


async def clear_failed_login_attempts(db: AsyncSession, *, username: str, client_ip: str) -> None:
    """Handle clear failed login attempts for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        username: username keyword value used by this routine (type `str`).
        client_ip: client ip keyword value used by this routine (type `str`).

    Returns:
        None. The routine is executed for its side effects.
    """
    await db.execute(
        delete(AuthLoginAttempt).where(
            AuthLoginAttempt.username == username,
            AuthLoginAttempt.client_ip == client_ip,
            AuthLoginAttempt.was_successful.is_(False),
        )
    )


async def cleanup_auth_data(db: AsyncSession) -> dict[str, int]:
    """Handle cleanup auth data for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).

    Returns:
        `dict[str, int]` result produced by the routine.
    """
    now = utcnow()
    session_cutoff = now - timedelta(days=settings.auth_session_retention_days)
    attempt_cutoff = now - timedelta(days=settings.auth_login_attempt_retention_days)

    deleted_sessions = await db.execute(
        delete(AuthSession).where(
            (AuthSession.expires_at < session_cutoff)
            | ((AuthSession.revoked_at.is_not(None)) & (AuthSession.revoked_at < session_cutoff))
        )
    )
    deleted_attempts = await db.execute(
        delete(AuthLoginAttempt).where(AuthLoginAttempt.attempted_at < attempt_cutoff)
    )
    await db.commit()
    return {
        "auth_sessions_deleted": int(deleted_sessions.rowcount or 0),
        "auth_login_attempts_deleted": int(deleted_attempts.rowcount or 0),
    }


async def list_sessions_for_admin(
    db: AsyncSession,
    *,
    username: str | None = None,
    include_revoked: bool = False,
) -> list[tuple[AuthSession, User]]:
    """Return a list of sessions for admin for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        username: username keyword value used by this routine (type `str | None`, optional).
        include_revoked: include revoked keyword value used by this routine (type `bool`, optional).

    Returns:
        `list[tuple[AuthSession, User]]` result produced by the routine.
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
    """Handle revoke all sessions for user for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        user_id: user id keyword value used by this routine (type `int`).

    Returns:
        `int` result produced by the routine.
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


async def list_users_for_admin(db: AsyncSession) -> list[User]:
    """Return a list of users for admin for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).

    Returns:
        `list[User]` result produced by the routine.
    """
    rows = await db.scalars(select(User).order_by(User.username.asc()))
    return list(rows.all())


async def create_user_for_admin(
    db: AsyncSession,
    *,
    username: str,
    full_name: str,
    password: str,
    role: str,
) -> User:
    """Create user for admin for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        username: username keyword value used by this routine (type `str`).
        full_name: full name keyword value used by this routine (type `str`).
        password: password keyword value used by this routine (type `str`).
        role: role keyword value used by this routine (type `str`).

    Returns:
        `User` result produced by the routine.
    """
    normalized_username = username.strip().lower()
    existing = await db.scalar(select(User).where(User.username == normalized_username))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    validate_password_strength(password, username=normalized_username, full_name=full_name)
    user = User(
        username=normalized_username,
        full_name=full_name.strip(),
        password_hash=hash_password(password),
        role=role,
        is_active=True,
        password_changed_at=utcnow(),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_user_for_admin(
    db: AsyncSession,
    *,
    user_id: int,
    full_name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    disabled_reason: str | None = None,
) -> User:
    """Update user for admin for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        user_id: user id keyword value used by this routine (type `int`).
        full_name: full name keyword value used by this routine (type `str | None`, optional).
        role: role keyword value used by this routine (type `str | None`, optional).
        is_active: is active keyword value used by this routine (type `bool | None`, optional).
        disabled_reason: disabled reason keyword value used by this routine (type `str | None`, optional).

    Returns:
        `User` result produced by the routine.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if full_name is not None:
        user.full_name = full_name.strip()
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
        if is_active:
            user.disabled_at = None
            user.disabled_reason = None
        else:
            user.disabled_at = utcnow()
            user.disabled_reason = (disabled_reason or "Disabled by admin").strip()[:255]
            await revoke_all_sessions_for_user(db, user_id=user.id)
    elif disabled_reason is not None and user.disabled_at is not None:
        user.disabled_reason = disabled_reason.strip()[:255]
    await db.commit()
    await db.refresh(user)
    return user


async def reset_user_password_for_admin(db: AsyncSession, *, user_id: int, new_password: str) -> User:
    """Handle reset user password for admin for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        user_id: user id keyword value used by this routine (type `int`).
        new_password: new password keyword value used by this routine (type `str`).

    Returns:
        `User` result produced by the routine.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    validate_password_strength(new_password, username=user.username, full_name=user.full_name)
    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow()
    await db.commit()
    await revoke_all_sessions_for_user(db, user_id=user.id)
    await db.refresh(user)
    return user


async def change_password_for_user(
    db: AsyncSession,
    *,
    user_id: int,
    current_password: str,
    new_password: str,
    current_jwt_id: str | None,
) -> User:
    """Handle change password for user for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        user_id: user id keyword value used by this routine (type `int`).
        current_password: current password keyword value used by this routine (type `str`).
        new_password: new password keyword value used by this routine (type `str`).
        current_jwt_id: current jwt id keyword value used by this routine (type `str | None`).

    Returns:
        `User` result produced by the routine.
    """
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is invalid")
    validate_password_strength(new_password, username=user.username, full_name=user.full_name)
    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow()
    await db.commit()
    await revoke_other_sessions_for_user(db, user_id=user.id, current_jwt_id=current_jwt_id)
    await db.refresh(user)
    return user


async def build_auth_observability_summary(db: AsyncSession) -> dict[str, int]:
    """Build auth observability summary for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).

    Returns:
        `dict[str, int]` result produced by the routine.
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


async def _touch_session_if_due(db: AsyncSession, session: AuthSession) -> None:
    """Handle the internal touch session if due helper logic for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        session: session value used by this routine (type `AuthSession`).

    Returns:
        None. The routine is executed for its side effects.
    """
    now = utcnow()
    if session.last_seen_at >= now - timedelta(seconds=settings.auth_session_touch_interval_seconds):
        return
    session.last_seen_at = now
    await db.flush()


def _build_session_tokens(
    user: User,
    *,
    session_jti: str,
    refresh_nonce: str,
    refresh_expires_at: datetime,
    access_expires_at: datetime,
) -> SessionTokens:
    """Build session tokens for business services that coordinate repositories and domain workflows.

    Args:
        user: user value used by this routine (type `User`).
        session_jti: session jti keyword value used by this routine (type `str`).
        refresh_nonce: refresh nonce keyword value used by this routine (type `str`).
        refresh_expires_at: refresh expires at keyword value used by this routine (type `datetime`).
        access_expires_at: access expires at keyword value used by this routine (type `datetime`).

    Returns:
        `SessionTokens` result produced by the routine.
    """
    return SessionTokens(
        access_token=create_access_token(
            subject=user.id,
            username=user.username,
            role=user.role,
            jwt_id=session_jti,
            expires_at=access_expires_at,
            access_nonce=generate_session_jwt_id(),
        ),
        refresh_token=create_refresh_token(
            subject=user.id,
            username=user.username,
            role=user.role,
            jwt_id=session_jti,
            refresh_nonce=refresh_nonce,
            expires_at=refresh_expires_at,
        ),
        access_expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
    )


async def _authenticate_session_for_refresh(db: AsyncSession, token: str) -> tuple[AuthenticatedActor, TokenPayload]:
    """Handle the internal authenticate session for refresh helper logic for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        token: token value used by this routine (type `str`).

    Returns:
        `tuple[AuthenticatedActor, TokenPayload]` result produced by the routine.
    """
    try:
        payload = decode_access_token(token)
    except JWTValidationError:
        return await _get_user_from_legacy_token(db, token), _legacy_payload()
    if payload.token_type == "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return await _authenticate_refresh_token(db, token)


async def _authenticate_refresh_token(db: AsyncSession, token: str) -> tuple[AuthenticatedActor, TokenPayload]:
    """Handle the internal authenticate refresh token helper logic for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        token: token value used by this routine (type `str`).

    Returns:
        `tuple[AuthenticatedActor, TokenPayload]` result produced by the routine.
    """
    payload = decode_access_token(token)
    if payload.token_type != "refresh" or not payload.refresh_nonce:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    session = await _get_active_session_by_jwt_id(db, payload.jwt_id)
    if session.token_hash != hash_session_token(payload.refresh_nonce):
        session.revoked_at = utcnow()
        session.last_seen_at = utcnow()
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = await _get_active_user_for_session(db, session, subject=payload.subject)
    await _touch_session_if_due(db, session)
    return AuthenticatedActor(kind="user", role=user.role, user=user, session=session), payload


async def _get_active_session_by_jwt_id(db: AsyncSession, jwt_id: str) -> AuthSession:
    """Return active session by jwt id for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        jwt_id: jwt id value used by this routine (type `str`).

    Returns:
        `AuthSession` result produced by the routine.
    """
    session = await db.scalar(select(AuthSession).where(AuthSession.jwt_id == jwt_id))
    if session is None or session.revoked_at is not None or session.expires_at <= utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return session


async def _get_active_user_for_session(db: AsyncSession, session: AuthSession, *, subject: int) -> User:
    """Return active user for session for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        session: session value used by this routine (type `AuthSession`).
        subject: subject keyword value used by this routine (type `int`).

    Returns:
        `User` result produced by the routine.
    """
    user = await db.get(User, subject)
    if user is None or user.id != session.user_id or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive")
    return user


def _legacy_payload() -> TokenPayload:
    """Handle the internal legacy payload helper logic for business services that coordinate repositories and domain workflows.

    Returns:
        `TokenPayload` result produced by the routine.
    """
    return TokenPayload(
        token_type="refresh",
        subject=0,
        jwt_id="",
        username="legacy",
        role="viewer",
        refresh_nonce=None,
        issued_at=utcnow(),
        not_before=utcnow(),
        expires_at=utcnow(),
    )


async def _get_user_from_legacy_token(db: AsyncSession, token: str) -> AuthenticatedActor:
    """Return user from legacy token for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        token: token value used by this routine (type `str`).

    Returns:
        `AuthenticatedActor` result produced by the routine.
    """
    token_hash = hash_session_token(token)
    session = await db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
    if session is None or session.revoked_at is not None or session.expires_at <= utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive")

    return AuthenticatedActor(kind="user", role=user.role, user=user, session=session)
