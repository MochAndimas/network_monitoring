"""Define module logic for `backend/app/services/auth/admin.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.security import hash_password, validate_password_strength, verify_password
from ...core.time import utcnow
from ...models.user import User
from .sessions import revoke_all_sessions_for_user, revoke_other_sessions_for_user


async def list_users_for_admin(db: AsyncSession) -> list[User]:
    """Return paged user rows visible to administrative callers.

    Args:
        db: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

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
    """Create a user account and enforce role/password policy constraints.

    Args:
        db: Parameter input untuk routine ini.
        username: Parameter input untuk routine ini.
        full_name: Parameter input untuk routine ini.
        password: Parameter input untuk routine ini.
        role: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

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
    """Update account profile, role, and activation fields for a user.

    Args:
        db: Parameter input untuk routine ini.
        user_id: Parameter input untuk routine ini.
        full_name: Parameter input untuk routine ini.
        role: Parameter input untuk routine ini.
        is_active: Parameter input untuk routine ini.
        disabled_reason: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

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
    """Reset user password and rotate credential state as needed.

    Args:
        db: Parameter input untuk routine ini.
        user_id: Parameter input untuk routine ini.
        new_password: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

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
    """Change password for a user after validating old credentials.

    Args:
        db: Parameter input untuk routine ini.
        user_id: Parameter input untuk routine ini.
        current_password: Parameter input untuk routine ini.
        new_password: Parameter input untuk routine ini.
        current_jwt_id: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

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

