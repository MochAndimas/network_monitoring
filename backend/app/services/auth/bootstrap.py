"""Bootstrap auth helpers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.security import hash_password
from ...core.time import utcnow
from ...models.user import User


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
        password_changed_at=utcnow(),
    )
    db.add(user)
    await db.commit()
    return True

