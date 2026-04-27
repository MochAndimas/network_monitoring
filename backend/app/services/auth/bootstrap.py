"""Define module logic for `backend/app/services/auth/bootstrap.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.security import hash_password
from ...core.time import utcnow
from ...models.user import User


async def ensure_bootstrap_admin(db: AsyncSession) -> bool:
    """Ensure bootstrap admin account exists for first-run environments.

    Args:
        db: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

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
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return False
    return True

