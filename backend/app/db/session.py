"""Database engine, async session factory, and connectivity checks."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..core.config import settings


def _async_database_url(database_url: str) -> str:
    """Return async database url for database initialization and sessions."""
    if database_url.startswith("sqlite:///") and not database_url.startswith("sqlite+aiosqlite:///"):
        return database_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if database_url.startswith("mysql+pymysql://"):
        return database_url.replace("mysql+pymysql://", "mysql+aiomysql://", 1)
    if database_url.startswith("mysql://"):
        return database_url.replace("mysql://", "mysql+aiomysql://", 1)
    return database_url


def _engine_options(database_url: str) -> dict[str, object]:
    """Return engine options for database initialization and sessions."""
    options: dict[str, object] = {
        "future": True,
        "pool_pre_ping": True,
    }
    if database_url.startswith("sqlite+aiosqlite:///"):
        return options
    database_settings = settings.database
    options.update(
        {
            "pool_size": database_settings.pool_size,
            "max_overflow": database_settings.max_overflow,
            "pool_timeout": database_settings.pool_timeout_seconds,
            "pool_recycle": database_settings.pool_recycle_seconds,
            "pool_use_lifo": True,
        }
    )
    return options


_resolved_database_url = _async_database_url(settings.database.url)
engine = create_async_engine(_resolved_database_url, **_engine_options(_resolved_database_url))
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, autoflush=False, autocommit=False, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Return get db used by application logic."""
    async with SessionLocal() as db:
        yield db


async def check_database_connection() -> bool:
    """Check database connection for database initialization and sessions."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def database_pool_health() -> dict[str, int | None]:
    """Return safe SQLAlchemy pool counters for System Health."""
    pool = engine.pool
    for attribute in ("size", "checkedout", "overflow"):
        if not hasattr(pool, attribute):
            return {"size": None, "checked_out": None, "overflow": None, "capacity": None}
    size = int(pool.size())
    checked_out = int(pool.checkedout())
    # QueuePool reports a negative overflow while fewer than pool_size
    # connections have been created; expose usage, not that implementation detail.
    overflow = max(int(pool.overflow()), 0)
    return {
        "size": size,
        "checked_out": checked_out,
        "overflow": overflow,
        "capacity": size + max(settings.database.max_overflow, 0),
    }
