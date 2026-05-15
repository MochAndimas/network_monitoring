"""Service-layer workflows for authentication."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.security import (
    JWTValidationError,
    TokenPayload,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    generate_session_jwt_id,
    hash_session_token,
    session_expiry,
    verify_password,
)
from ...core.time import utcnow
from ...models.user import AuthLoginAttempt, AuthSession, User
from .types import AuthenticatedActor, SessionTokens


async def authenticate_user(db: AsyncSession, username: str, password: str) -> tuple[User, str, datetime]:
    """Authenticate user in the service layer."""
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
    commit: bool = True,
) -> tuple[User, SessionTokens]:
    """Authenticate user with options in the service layer."""
    normalized_username = username.strip().lower()
    await ensure_login_not_rate_limited(db, username=normalized_username, client_ip=client_ip)
    user = await db.scalar(select(User).where(User.username == normalized_username))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        await record_login_attempt(
            db,
            username=normalized_username,
            client_ip=client_ip,
            was_successful=False,
            commit=commit,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    session_jti = generate_session_jwt_id()
    refresh_nonce = generate_session_jwt_id()
    auth_settings = settings.auth
    refresh_expires_at = session_expiry(
        auth_settings.remember_ttl_minutes if remember else auth_settings.token_ttl_minutes
    )
    access_expires_at = min(session_expiry(auth_settings.token_ttl_minutes), refresh_expires_at)
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
    if commit:
        await db.commit()
    else:
        await db.flush()
    return user, _build_session_tokens(
        user,
        session_jti=session_jti,
        refresh_nonce=refresh_nonce,
        refresh_expires_at=refresh_expires_at,
        access_expires_at=access_expires_at,
    )


async def authenticate_token(db: AsyncSession, token: str) -> tuple[User, AuthSession]:
    """Authenticate token in the service layer."""
    actor = await get_user_from_access_token(db, token)
    if actor.user is None or actor.session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return actor.user, actor.session


async def refresh_user_session(
    db: AsyncSession,
    refresh_token: str,
    *,
    commit: bool = True,
) -> tuple[User, SessionTokens]:
    """Refresh user session in the service layer."""
    actor, payload = await _authenticate_session_for_refresh(db, refresh_token, commit=commit)
    if actor.user is None or actor.session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    session_jti = actor.session.jwt_id or payload.jwt_id or generate_session_jwt_id()
    new_refresh_nonce = generate_session_jwt_id()
    actor.session.jwt_id = session_jti
    actor.session.token_hash = hash_session_token(new_refresh_nonce)
    actor.session.last_seen_at = utcnow()
    refresh_expires_at = actor.session.expires_at
    access_expires_at = min(session_expiry(settings.auth.token_ttl_minutes), refresh_expires_at)
    if commit:
        await db.commit()
    else:
        await db.flush()
    tokens = _build_session_tokens(
        actor.user,
        session_jti=session_jti,
        refresh_nonce=new_refresh_nonce,
        refresh_expires_at=refresh_expires_at,
        access_expires_at=access_expires_at,
    )
    return actor.user, tokens


def actor_has_permission(actor: AuthenticatedActor, permission: str) -> bool:
    """Return actor has permission used by service-layer code."""
    if actor.user is not None:
        return actor.role == "admin"
    return permission in actor.permissions


async def get_user_from_access_token(db: AsyncSession, token: str) -> AuthenticatedActor:
    """Return get user from access token used by authentication and session management."""
    try:
        payload = decode_access_token(token)
    except JWTValidationError:
        return await _get_user_from_legacy_token(db, token)
    if payload.token_type != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    session = await _get_active_session_by_jwt_id(db, payload.jwt_id)
    user = await _get_active_user_for_session(db, session, subject=payload.subject)
    return AuthenticatedActor(kind="user", role=user.role, user=user, session=session)


async def get_user_from_refresh_token(
    db: AsyncSession,
    token: str,
    *,
    commit: bool = True,
) -> AuthenticatedActor:
    """Return get user from refresh token used by authentication and session management."""
    try:
        actor, _payload = await _authenticate_refresh_token(db, token, commit=commit)
    except JWTValidationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc
    return actor


async def get_user_from_token(db: AsyncSession, token: str) -> AuthenticatedActor:
    """Return get user from token used by authentication and session management."""
    try:
        payload = decode_access_token(token)
    except JWTValidationError:
        return await _get_user_from_legacy_token(db, token)
    if payload.token_type == "refresh":
        return await get_user_from_refresh_token(db, token)
    return await get_user_from_access_token(db, token)


async def revoke_token(db: AsyncSession, token: str, *, commit: bool = True) -> None:
    """Revoke a session token if it maps to an active stored session."""
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
    if commit:
        await db.commit()
    else:
        await db.flush()


async def ensure_login_not_rate_limited(db: AsyncSession, *, username: str, client_ip: str) -> None:
    """Ensure login not rate limited in the service layer."""
    auth_settings = settings.auth
    window_start = utcnow() - timedelta(minutes=auth_settings.login_rate_limit_window_minutes)
    failed_attempts = await db.scalar(
        select(func.count(AuthLoginAttempt.id)).where(
            AuthLoginAttempt.username == username,
            AuthLoginAttempt.client_ip == client_ip,
            AuthLoginAttempt.was_successful.is_(False),
            AuthLoginAttempt.attempted_at >= window_start,
        )
    )
    if int(failed_attempts or 0) >= auth_settings.login_rate_limit_max_attempts:
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
    commit: bool = True,
) -> None:
    """Record login attempt in the service layer."""
    db.add(
        AuthLoginAttempt(
            username=username,
            client_ip=client_ip,
            was_successful=was_successful,
            was_rate_limited=was_rate_limited,
            attempted_at=utcnow(),
        )
    )
    if commit:
        await db.commit()
    else:
        await db.flush()


async def clear_failed_login_attempts(db: AsyncSession, *, username: str, client_ip: str) -> None:
    """Clear failed login attempts in the service layer."""
    await db.execute(
        delete(AuthLoginAttempt).where(
            AuthLoginAttempt.username == username,
            AuthLoginAttempt.client_ip == client_ip,
            AuthLoginAttempt.was_successful.is_(False),
        )
    )


async def _touch_session_if_due(db: AsyncSession, session: AuthSession) -> None:
    """Touch session if due in the service layer."""
    now = utcnow()
    if session.last_seen_at >= now - timedelta(seconds=settings.auth.session_touch_interval_seconds):
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
    """Build session tokens in the service layer."""
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


async def _authenticate_session_for_refresh(
    db: AsyncSession,
    token: str,
    *,
    commit: bool = True,
) -> tuple[AuthenticatedActor, TokenPayload]:
    """Authenticate session for refresh in the service layer."""
    try:
        payload = decode_access_token(token)
    except JWTValidationError:
        return await _get_user_from_legacy_token(db, token), _legacy_payload()
    if payload.token_type == "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return await _authenticate_refresh_token(db, token, commit=commit)


async def _authenticate_refresh_token(
    db: AsyncSession,
    token: str,
    *,
    commit: bool = True,
) -> tuple[AuthenticatedActor, TokenPayload]:
    """Authenticate refresh token in the service layer."""
    payload = decode_access_token(token)
    if payload.token_type != "refresh" or not payload.refresh_nonce:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    session = await _get_active_session_by_jwt_id(db, payload.jwt_id)
    if session.token_hash != hash_session_token(payload.refresh_nonce):
        session.revoked_at = utcnow()
        session.last_seen_at = utcnow()
        if commit:
            await db.commit()
        else:
            await db.flush()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = await _get_active_user_for_session(db, session, subject=payload.subject)
    await _touch_session_if_due(db, session)
    return AuthenticatedActor(kind="user", role=user.role, user=user, session=session), payload


async def _get_active_session_by_jwt_id(db: AsyncSession, jwt_id: str) -> AuthSession:
    """Return get active session by jwt id used by authentication and session management."""
    session = await db.scalar(select(AuthSession).where(AuthSession.jwt_id == jwt_id))
    if session is None or session.revoked_at is not None or session.expires_at <= utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return session


async def _get_active_user_for_session(db: AsyncSession, session: AuthSession, *, subject: int) -> User:
    """Return get active user for session used by authentication and session management."""
    user = await db.get(User, subject)
    if user is None or user.id != session.user_id or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive")
    return user


def _legacy_payload() -> TokenPayload:
    """Return legacy payload used by service-layer code."""
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
    """Return get user from legacy token used by authentication and session management."""
    token_hash = hash_session_token(token)
    session = await db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
    if session is None or session.revoked_at is not None or session.expires_at <= utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive")

    return AuthenticatedActor(kind="user", role=user.role, user=user, session=session)

