from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.security import generate_session_token, hash_password, hash_session_token, session_expiry, verify_password
from ..core.time import utcnow
from ..models.user import AuthSession, User


@dataclass(slots=True)
class AuthenticatedActor:
    kind: str
    role: str
    user: User | None = None
    session: AuthSession | None = None


async def ensure_bootstrap_admin(db: AsyncSession) -> bool:
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
    )
    db.add(user)
    await db.commit()
    return True


async def authenticate_user(db: AsyncSession, username: str, password: str) -> tuple[User, str, datetime]:
    normalized_username = username.strip().lower()
    user = await db.scalar(select(User).where(User.username == normalized_username))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token = generate_session_token()
    expiry = session_expiry()
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=expiry,
            last_seen_at=utcnow(),
        )
    )
    await db.commit()
    return user, token, expiry


async def get_user_from_token(db: AsyncSession, token: str) -> AuthenticatedActor:
    token_hash = hash_session_token(token)
    session = await db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
    if session is None or session.revoked_at is not None or session.expires_at <= utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive")

    session.last_seen_at = utcnow()
    await db.commit()
    return AuthenticatedActor(kind="user", role=user.role, user=user, session=session)


async def revoke_token(db: AsyncSession, token: str) -> None:
    token_hash = hash_session_token(token)
    session = await db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
    if session is None:
        return
    session.revoked_at = utcnow()
    await db.commit()
