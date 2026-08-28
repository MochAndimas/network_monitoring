"""Unit tests for collector retry/backpressure safeguards."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from backend.app.monitors import helpers


def test_retry_transient_collection_retries_only_transient_statuses(monkeypatch):
    async def scenario():
        attempts = 0

        async def operation():
            nonlocal attempts
            attempts += 1
            return SimpleNamespace(collection_status="timeout" if attempts == 1 else "ok")

        result = await helpers.retry_transient_collection(operation, retryable_statuses={"timeout"})
        assert result.collection_status == "ok"
        assert attempts == 2

    monkeypatch.setattr(
        helpers,
        "settings",
        SimpleNamespace(monitor=SimpleNamespace(collector_retry_attempts=2, collector_retry_backoff_seconds=0)),
    )
    asyncio.run(scenario())


def test_vendor_protocol_guard_applies_shared_limit(monkeypatch):
    async def scenario():
        active = 0
        peak = 0

        async def operation():
            nonlocal active, peak
            async with helpers.vendor_protocol_guard("test-snmp", limit=2):
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0)
                active -= 1

        await asyncio.gather(*(operation() for _ in range(8)))
        assert peak == 2

    helpers._VENDOR_PROTOCOL_SEMAPHORES.clear()
    asyncio.run(scenario())
