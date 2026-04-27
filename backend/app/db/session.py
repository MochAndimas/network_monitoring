"""Define module logic for `backend/app/db/session.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..core.config import settings


def _async_database_url(database_url: str) -> str:
    """Perform async database url.

    Args:
        database_url: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    if database_url.startswith("sqlite:///") and not database_url.startswith("sqlite+aiosqlite:///"):
        return database_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if database_url.startswith("mysql+pymysql://"):
        return database_url.replace("mysql+pymysql://", "mysql+aiomysql://", 1)
    if database_url.startswith("mysql://"):
        return database_url.replace("mysql://", "mysql+aiomysql://", 1)
    return database_url


def _engine_options(database_url: str) -> dict[str, object]:
    """Perform engine options.

    Args:
        database_url: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    options: dict[str, object] = {
        "future": True,
        "pool_pre_ping": True,
    }
    if database_url.startswith("sqlite+aiosqlite:///"):
        return options
    options.update(
        {
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_timeout": settings.db_pool_timeout_seconds,
            "pool_recycle": settings.db_pool_recycle_seconds,
            "pool_use_lifo": True,
        }
    )
    return options


_resolved_database_url = _async_database_url(settings.database_url)
engine = create_async_engine(_resolved_database_url, **_engine_options(_resolved_database_url))
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, autoflush=False, autocommit=False, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped async database session.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    async with SessionLocal() as db:
        yield db


async def check_database_connection() -> bool:
    """Return True when a simple database query succeeds.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
