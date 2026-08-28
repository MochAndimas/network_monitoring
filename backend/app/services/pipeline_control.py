"""Service-layer workflows for pipeline control."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import AsyncExitStack, asynccontextmanager
from collections.abc import AsyncIterator
import logging
import re

from sqlalchemy import text

from ..core.config import settings
from ..db.session import engine


_monitoring_pipeline_locks: dict[str, asyncio.Lock] = {}
_pipeline_lock_contention_count = 0
logger = logging.getLogger("network_monitoring.pipeline")
MONITORING_METRIC_LOCK_SCOPES = ("metrics:internet", "metrics:device", "metrics:server", "metrics:mikrotik")
MONITORING_ALERT_LOCK_SCOPE = "alerts"
MONITORING_CLEANUP_LOCK_SCOPE = "cleanup"
MONITORING_FULL_CYCLE_LOCK_SCOPES = (
    *MONITORING_METRIC_LOCK_SCOPES,
    MONITORING_ALERT_LOCK_SCOPE,
    MONITORING_CLEANUP_LOCK_SCOPE,
)


def _mysql_lock_timeout_seconds(*, wait: bool) -> int:
    """Return the MySQL advisory lock timeout for blocking or non-blocking calls."""
    return max(settings.monitor.lock_timeout_seconds, 1) if wait else 0


def _normalized_lock_scope(scope: str | None) -> str:
    """Normalize a caller-provided lock scope into a stable advisory-lock suffix."""
    normalized = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", str(scope or "pipeline").strip())
    return normalized or "pipeline"


def _scoped_lock_name(scope: str | None) -> str:
    """Return the configured lock name with a scope suffix for independent work streams."""
    normalized_scope = _normalized_lock_scope(scope)
    base_name = settings.monitor.lock_name.rstrip(".")
    lock_name = base_name if normalized_scope == "pipeline" else f"{base_name}.{normalized_scope}"
    if len(lock_name) <= 64:
        return lock_name
    digest = hashlib.sha1(lock_name.encode("utf-8")).hexdigest()[:16]
    return f"{lock_name[:47]}.{digest}"


def _process_lock_for_scope(scope: str | None) -> asyncio.Lock:
    """Return the process-local asyncio lock for one monitoring scope."""
    normalized_scope = _normalized_lock_scope(scope)
    lock = _monitoring_pipeline_locks.get(normalized_scope)
    current_loop = asyncio.get_running_loop()
    lock_loop = getattr(lock, "_loop", None) if lock is not None else None
    if lock is not None and lock_loop is not None and lock_loop is not current_loop and not lock.locked():
        lock = None
    if lock is None:
        lock = asyncio.Lock()
        _monitoring_pipeline_locks[normalized_scope] = lock
    return lock


def _ordered_unique_scopes(scopes: list[str | None] | tuple[str | None, ...]) -> list[str | None]:
    """Return lock scopes in a deterministic order to avoid multi-lock deadlocks."""
    unique_scopes = {
        _normalized_lock_scope(scope): scope
        for scope in scopes
    }
    return [
        unique_scopes[normalized_scope]
        for normalized_scope in sorted(unique_scopes)
    ]


async def _acquire_mysql_lock(*, wait: bool, scope: str | None) -> tuple[object | None, bool]:
    """Acquire the named MySQL advisory lock for monitoring work."""
    connection = await engine.connect()
    try:
        result = await connection.execute(
            text("SELECT GET_LOCK(:lock_name, :timeout_seconds)"),
            {
                "lock_name": _scoped_lock_name(scope),
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


async def _release_mysql_lock(connection, *, scope: str | None) -> None:
    """Release the named MySQL advisory lock and close its connection."""
    try:
        await connection.execute(
            text("SELECT RELEASE_LOCK(:lock_name)"),
            {"lock_name": _scoped_lock_name(scope)},
        )
    finally:
        await connection.close()


@asynccontextmanager
async def monitoring_pipeline_guard(*, wait: bool, scope: str | None = None) -> AsyncIterator[bool]:
    """Acquire the process or MySQL lock for one monitoring work scope."""
    global _pipeline_lock_contention_count
    if engine.dialect.name == "mysql":
        connection, acquired = await _acquire_mysql_lock(wait=wait, scope=scope)
        if not acquired:
            _pipeline_lock_contention_count += 1
        try:
            yield acquired
        finally:
            if acquired and connection is not None:
                await _release_mysql_lock(connection, scope=scope)
        return

    process_lock = _process_lock_for_scope(scope)
    acquired = False
    if wait:
        await process_lock.acquire()
        acquired = True
    else:
        try:
            await asyncio.wait_for(process_lock.acquire(), timeout=0.001)
            acquired = True
        except TimeoutError:
            acquired = False
            _pipeline_lock_contention_count += 1

    try:
        yield acquired
    finally:
        if acquired:
            process_lock.release()


def pipeline_lock_health() -> dict[str, int]:
    """Return process-local lock contention observations for the active worker."""
    return {"contention_count": _pipeline_lock_contention_count}


@asynccontextmanager
async def monitoring_pipeline_multi_guard(
    *,
    wait: bool,
    scopes: list[str | None] | tuple[str | None, ...],
) -> AsyncIterator[bool]:
    """Acquire several monitoring lock scopes as one coordinated critical section."""
    ordered_scopes = _ordered_unique_scopes(tuple(scopes))
    async with AsyncExitStack() as stack:
        for scope in ordered_scopes:
            acquired = await stack.enter_async_context(monitoring_pipeline_guard(wait=wait, scope=scope))
            if not acquired:
                logger.info(
                    "Skipping monitoring multi-scope guard because scope is active scope=%s scopes=%s",
                    _normalized_lock_scope(scope),
                    ",".join(_normalized_lock_scope(item) for item in ordered_scopes),
                )
                yield False
                return
        yield True
