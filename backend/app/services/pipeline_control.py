"""Service-layer workflows for pipeline control."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import AsyncExitStack, asynccontextmanager
from collections.abc import AsyncIterator
import logging
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..core.config import settings
from ..db.session import engine
from .collector_ownership import device_collector_ownership


_monitoring_pipeline_locks: dict[str, asyncio.Lock] = {}
_pipeline_lock_contention_count = 0
logger = logging.getLogger("network_monitoring.pipeline")
MONITORING_METRIC_LOCK_SCOPES = ("metrics:internet", "metrics:device:central", "metrics:server", "metrics:mikrotik")
MONITORING_ALERT_LOCK_SCOPE = "alerts"
MONITORING_CLEANUP_LOCK_SCOPE = "cleanup"
MONITORING_FULL_CYCLE_LOCK_SCOPES = (
    *MONITORING_METRIC_LOCK_SCOPES,
    MONITORING_ALERT_LOCK_SCOPE,
    MONITORING_CLEANUP_LOCK_SCOPE,
)


def monitoring_full_cycle_lock_scopes() -> tuple[str, ...]:
    """Use the same device owner as the scheduler on this process."""
    ownership = device_collector_ownership()
    device_scope = f"metrics:{ownership.lock_scope}"
    if ownership.site is not None:
        return (device_scope, MONITORING_ALERT_LOCK_SCOPE)
    return tuple(
        device_scope if scope == "metrics:device:central" else scope for scope in MONITORING_FULL_CYCLE_LOCK_SCOPES
    )


class PipelineLockTimeoutError(TimeoutError):
    """Blocking acquisition failed; the protected operation must not run."""

    def __init__(self, scope: str | None) -> None:
        self.scope = _normalized_lock_scope(scope)
        super().__init__(f"Timed out acquiring monitoring lock scope={self.scope}")


def _lock_timeout_seconds(*, wait: bool) -> int:
    """Return the shared timeout for blocking or non-blocking lock calls."""
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
    # Non-security identifier: preserve the same advisory lock across old/new workers.
    # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
    digest = hashlib.sha1(lock_name.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
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
    unique_scopes = {_normalized_lock_scope(scope): scope for scope in scopes}
    return [unique_scopes[normalized_scope] for normalized_scope in sorted(unique_scopes)]


async def _acquire_mysql_lock(*, wait: bool, scope: str | None) -> tuple[AsyncConnection | None, bool]:
    """Acquire the named MySQL advisory lock for monitoring work."""
    connection = await engine.connect()
    try:
        result = await connection.execute(
            text("SELECT GET_LOCK(:lock_name, :timeout_seconds)"),
            {
                "lock_name": _scoped_lock_name(scope),
                "timeout_seconds": _lock_timeout_seconds(wait=wait),
            },
        )
        acquired = bool(result.scalar())
        if not acquired:
            await connection.close()
            return None, False
        return connection, True
    except BaseException:
        # A cancelled/failed GET_LOCK can leave ownership uncertain. Discard
        # the physical connection instead of returning a named lock to the pool.
        try:
            await connection.invalidate()
        finally:
            await connection.close()
        raise


async def _release_mysql_lock(connection: AsyncConnection, *, scope: str | None) -> None:
    """Release the named MySQL advisory lock and close its connection."""
    try:
        await connection.execute(
            text("SELECT RELEASE_LOCK(:lock_name)"),
            {"lock_name": _scoped_lock_name(scope)},
        )
    except BaseException:
        await connection.invalidate()
        raise
    finally:
        await connection.close()


@asynccontextmanager
async def monitoring_pipeline_guard(*, wait: bool, scope: str | None = None) -> AsyncIterator[bool]:
    """Yield ownership; blocking timeout raises before entering the caller body.

    Non-blocking callers must check the yielded boolean. Blocking callers may
    assume ownership in the body, on both MySQL and the process-local fallback.
    """
    global _pipeline_lock_contention_count
    if engine.dialect.name == "mysql":
        connection, acquired = await _acquire_mysql_lock(wait=wait, scope=scope)
        if not acquired:
            _pipeline_lock_contention_count += 1
            if wait:
                raise PipelineLockTimeoutError(scope)
        try:
            yield acquired
        finally:
            if acquired and connection is not None:
                await _release_mysql_lock(connection, scope=scope)
        return

    process_lock = _process_lock_for_scope(scope)
    acquired = False
    if wait:
        try:
            await asyncio.wait_for(process_lock.acquire(), timeout=_lock_timeout_seconds(wait=True))
        except TimeoutError as exc:
            _pipeline_lock_contention_count += 1
            raise PipelineLockTimeoutError(scope) from exc
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
