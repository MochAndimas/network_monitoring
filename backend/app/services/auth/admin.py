"""Service-layer workflows for admin."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.security import hash_password, validate_password_strength, verify_password
from ...core.time import utcnow
from ...models.user import User
from .sessions import revoke_all_sessions_for_user, revoke_other_sessions_for_user


async def list_users_for_admin(db: AsyncSession) -> list[User]:
    """List users for admin in the service layer."""
    rows = await db.scalars(select(User).order_by(User.username.asc()))
    return list(rows.all())


async def create_user_for_admin(
    db: AsyncSession,
    *,
    username: str,
    full_name: str,
    password: str,
    role: str,
    commit: bool = True,
) -> User:
    """Create user for admin in the service layer."""
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
    await db.flush()
    if commit:
        await db.commit()
        await db.refresh(user)
    return user


async def update_user_for_admin(
    db: AsyncSession,
    *,
    user_id: int,
    actor_user_id: int | None = None,
    full_name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    disabled_reason: str | None = None,
    commit: bool = True,
) -> User:
    """Update user for admin in the service layer."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    removes_last_active_admin = (
        user.role == "admin"
        and user.is_active
        and (role is not None and role != "admin" or is_active is False)
    )
    if removes_last_active_admin:
        active_admins = await db.scalar(select(func.count(User.id)).where(User.role == "admin", User.is_active.is_(True)))
        if int(active_admins or 0) <= 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The last active administrator cannot be changed")
    if actor_user_id == user.id and is_active is False:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot disable your own account")
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
            await revoke_all_sessions_for_user(db, user_id=user.id, commit=False)
    elif disabled_reason is not None and user.disabled_at is not None:
        user.disabled_reason = disabled_reason.strip()[:255]
    await db.flush()
    if commit:
        await db.commit()
        await db.refresh(user)
    return user


async def reset_user_password_for_admin(
    db: AsyncSession,
    *,
    user_id: int,
    new_password: str,
    commit: bool = True,
) -> User:
    """Reset a user's password and revoke sessions in one transaction."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    validate_password_strength(new_password, username=user.username, full_name=user.full_name)
    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow()
    await revoke_all_sessions_for_user(db, user_id=user.id, commit=False)
    await db.flush()
    if commit:
        await db.commit()
        await db.refresh(user)
    return user


async def update_profile_for_user(
    db: AsyncSession,
    *,
    user_id: int,
    full_name: str,
    commit: bool = True,
) -> User:
    """Update the profile fields a user is allowed to manage themselves."""
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.full_name = full_name.strip()
    await db.flush()
    if commit:
        await db.commit()
        await db.refresh(user)
    return user


async def delete_user_for_admin(
    db: AsyncSession,
    *,
    user_id: int,
    actor_user_id: int | None,
    commit: bool = True,
) -> User:
    """Permanently delete a non-current user while preserving one active administrator."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if actor_user_id == user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account")
    if user.role == "admin" and user.is_active:
        active_admins = await db.scalar(select(func.count(User.id)).where(User.role == "admin", User.is_active.is_(True)))
        if int(active_admins or 0) <= 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The last active administrator cannot be deleted")
    await db.delete(user)
    await db.flush()
    if commit:
        await db.commit()
    return user


async def change_password_for_user(
    db: AsyncSession,
    *,
    user_id: int,
    current_password: str,
    new_password: str,
    current_jwt_id: str | None,
    commit: bool = True,
) -> User:
    """Change a user's own password and revoke other sessions atomically."""
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is invalid")
    validate_password_strength(new_password, username=user.username, full_name=user.full_name)
    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow()
    await revoke_other_sessions_for_user(
        db,
        user_id=user.id,
        current_jwt_id=current_jwt_id,
        commit=False,
    )
    await db.flush()
    if commit:
        await db.commit()
        await db.refresh(user)
    return user
