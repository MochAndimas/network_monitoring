"""Define test module behavior for `tests/test_utils.py`.

This module contains automated regression and validation scenarios.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from backend.app.db.base import Base


def run(coro):
    if sys.platform.startswith("win"):
        policy_factory = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
        if policy_factory is not None:
            asyncio.set_event_loop_policy(policy_factory())
    return asyncio.run(coro)


async def create_all(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def drop_all(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def empty_checks(db: AsyncSession, **_options: object) -> list[dict]:
    return []


def make_fake_safe_ping(samples: Iterable[float | None]):
    sample_iter = iter(samples)

    async def _fake_safe_ping(_ip_address):
        return next(sample_iter)

    return _fake_safe_ping
