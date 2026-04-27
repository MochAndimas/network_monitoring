"""Define module logic for `backend/app/services/pipeline_control.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import logging

from sqlalchemy import text

from ..core.config import settings
from ..db.session import engine


_monitoring_pipeline_lock = asyncio.Lock()
logger = logging.getLogger("network_monitoring.pipeline")


def _mysql_lock_timeout_seconds(*, wait: bool) -> int:
    """Perform mysql lock timeout seconds.

    Args:
        wait: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    return max(settings.monitoring_lock_timeout_seconds, 1) if wait else 0


async def _acquire_mysql_lock(*, wait: bool) -> tuple[object | None, bool]:
    """Perform acquire mysql lock.

    Args:
        wait: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    connection = await engine.connect()
    try:
        result = await connection.execute(
            text("SELECT GET_LOCK(:lock_name, :timeout_seconds)"),
            {
                "lock_name": settings.monitoring_lock_name,
                "timeout_seconds": _mysql_lock_timeout_seconds(wait=wait),
            },
        )
        acquired = bool(result.scalar())
        if not acquired:
            await connection.close()
            return None, False
        return connection, True
    except Exception:
        await connection.close()
        raise


async def _release_mysql_lock(connection) -> None:
    """Perform release mysql lock.

    Args:
        connection: Parameter input untuk routine ini.

    """
    try:
        await connection.execute(
            text("SELECT RELEASE_LOCK(:lock_name)"),
            {"lock_name": settings.monitoring_lock_name},
        )
    finally:
        await connection.close()


@asynccontextmanager
async def monitoring_pipeline_guard(*, wait: bool) -> AsyncIterator[bool]:
    """Guard monitoring pipeline execution with cooperative distributed locking.

    Args:
        wait: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    if engine.dialect.name == "mysql":
        connection, acquired = await _acquire_mysql_lock(wait=wait)
        try:
            yield acquired
        finally:
            if acquired and connection is not None:
                await _release_mysql_lock(connection)
        return

    acquired = False
    if wait:
        await _monitoring_pipeline_lock.acquire()
        acquired = True
    else:
        try:
            await asyncio.wait_for(_monitoring_pipeline_lock.acquire(), timeout=0.001)
            acquired = True
        except TimeoutError:
            acquired = False

    try:
        yield acquired
    finally:
        if acquired:
            _monitoring_pipeline_lock.release()
