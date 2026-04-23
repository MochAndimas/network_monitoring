"""Shared helpers for test suites."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncEngine

from backend.app.db.base import Base


def run(coro):
    return asyncio.run(coro)


async def create_all(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def drop_all(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def empty_checks(_db):
    return []


def make_fake_safe_ping(samples: Iterable[float | None]):
    sample_iter = iter(samples)

    async def _fake_safe_ping(_ip_address):
        return next(sample_iter)

    return _fake_safe_ping

