"""Single-router polling never broadens collection or persists partial reads."""

from dataclasses import replace
from time import time_ns

import pytest
from sqlalchemy import select

from backend.app.bandwidth import inventory_worker as worker
from backend.app.core.config import settings
from backend.app.models.bandwidth import BandwidthClient, BandwidthInventoryState
from tests.test_utils import run


@pytest.mark.parametrize("fail", [False, True])
def test_scan_cursor_advances_after_commit_and_continues_zero_matches(inventory_sessions, monkeypatch, fail):
    from backend.app.bandwidth.discovery import InventorySnapshot
    from backend.app.services.bandwidth_reconciliation_service import ReconciliationCursor

    target = replace(settings.mikrotik, host="192.0.2.1")
    cursor = ReconciliationCursor(after_id=10, upper_id=100)
    calls = []
    monkeypatch.setattr(worker, "read_snapshot", lambda *args: InventorySnapshot(1, time_ns(), (), (), 0))

    async def reconcile(db, router_id, *, cursor):
        calls.append(cursor.after_id)
        cursor.after_id += 1
        if fail:
            raise RuntimeError("rollback")
        if len(calls) == 3:
            cursor.after_id, cursor.upper_id = 0, None
        return 0

    monkeypatch.setattr(worker, "reconcile_identities", reconcile)
    if fail:
        with pytest.raises(RuntimeError, match="rollback"):
            run(worker.poll_once(inventory_sessions, 1, target, "lan", 120, reconciliation_cursor=cursor))
        assert cursor == ReconciliationCursor(after_id=10, upper_id=100)
    else:
        run(worker.poll_once(inventory_sessions, 1, target, "lan", 120, reconciliation_cursor=cursor))
        assert calls == [10, 11, 12]
        assert cursor == ReconciliationCursor()


def test_complete_reads_close_api_and_partial_failure_is_not_published(monkeypatch):
    calls = []

    class API:
        def path(self, *parts):
            calls.append(parts)
            if parts == ("ip", "arp"):
                raise TimeoutError("private connection details")
            return []

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(worker, "connect", lambda **kwargs: API())
    with pytest.raises(TimeoutError):
        worker.read_snapshot(1, settings.mikrotik, "10.10.10.1")
    assert calls == [("ip", "dhcp-server", "lease"), ("ip", "arp"), "closed"]


def test_scoped_poll_persists_identity_and_failed_poll_preserves_observation(inventory_sessions, monkeypatch):
    calls = []
    target = replace(settings.mikrotik, host="192.0.2.1", username="fixture", password="private")
    fail = False

    class API:
        def path(self, *parts):
            if fail:
                raise ConnectionError("private")
            if parts == ("ip", "dhcp-server", "lease"):
                return [{"address": "192.168.1.31", "mac-address": "70:08:94:1B:9C:DF", "status": "bound"}]
            return []

        def close(self):
            pass

    def connect(**kwargs):
        calls.append(kwargs["host"])
        return API()

    monkeypatch.setattr(worker, "connect", connect)

    async def exercise():
        nonlocal fail
        await worker.poll_once(inventory_sessions, 1, target, "10.10.10.1", 120)
        async with inventory_sessions() as db:
            observed = await db.scalar(select(BandwidthInventoryState.observed_ns))
            clients = list(await db.scalars(select(BandwidthClient)))
            assert len(clients) == 1 and clients[0].router_id == 1
        fail = True
        with pytest.raises(ConnectionError):
            await worker.poll_once(inventory_sessions, 1, target, "10.10.10.1", 120)
        async with inventory_sessions() as db:
            assert await db.scalar(select(BandwidthInventoryState.observed_ns)) == observed
        with pytest.raises(ValueError, match="target_router_mismatch"):
            await worker.poll_once(inventory_sessions, 2, target, "10.10.10.1", 120)

    run(exercise())
    assert calls == ["10.10.10.1", "10.10.10.1"]


def test_snapshot_health_rejects_missing_stale_future_and_other_router(inventory_sessions):
    async def exercise():
        assert not await worker.snapshot_fresh(inventory_sessions, 1, 120)
        for observed, expected in ((time_ns(), True), (time_ns() - 121 * 10**9, False), (time_ns() + 10**9, False)):
            async with inventory_sessions.begin() as db:
                await db.merge(
                    BandwidthInventoryState(
                        router_id=1, observed_ns=observed, client_count=0, ambiguous_ip_count=0, invalid_row_count=0
                    )
                )
            assert await worker.snapshot_fresh(inventory_sessions, 1, 120) is expected
            assert not await worker.snapshot_fresh(inventory_sessions, 2, 120)

    run(exercise())


def test_fallback_retries_vpn_and_never_commits_partial_or_wrong_router(inventory_sessions, monkeypatch):
    target = replace(settings.mikrotik, host="192.0.2.1", username="fixture", password="private")
    calls = []
    closed = []
    vpn_available = False
    wrong_lan = False

    class API:
        def __init__(self, host):
            self.host = host

        def path(self, *parts):
            if parts == ("system", "identity"):
                return [{"name": "Other router" if wrong_lan and self.host == "lan" else "Office"}]
            if parts == ("ip", "arp") and self.host == "vpn" and not vpn_available:
                raise ConnectionError("sensitive API error")
            if parts == ("ip", "dhcp-server", "lease"):
                return [{"address": "192.168.1.31", "mac-address": "70:08:94:1B:9C:DF", "status": "bound"}]
            return []

        def close(self):
            closed.append(self.host)

    def connect(**kwargs):
        calls.append((kwargs["host"], kwargs["port"]))
        return API(kwargs["host"])

    monkeypatch.setattr(worker, "connect", connect)

    async def poll():
        return await worker.poll_once(
            inventory_sessions,
            1,
            target,
            "vpn",
            120,
            fallback_host="lan",
            expected_identity="Office",
            api_port=8331,
            fallback_port=8728,
        )

    async def exercise():
        nonlocal vpn_available, wrong_lan
        assert await poll() == "lan"
        async with inventory_sessions() as db:
            observed = await db.scalar(select(BandwidthInventoryState.observed_ns))
            assert len(list(await db.scalars(select(BandwidthClient)))) == 1
        wrong_lan = True
        with pytest.raises(ValueError, match="identity_mismatch"):
            await poll()
        async with inventory_sessions() as db:
            assert await db.scalar(select(BandwidthInventoryState.observed_ns)) == observed
        vpn_available = True
        assert await poll() == "vpn"
        with pytest.raises(ValueError, match="requires_router_identity"):
            await worker.poll_once(inventory_sessions, 1, target, "vpn", 120, fallback_host="lan")

    run(exercise())
    assert calls == [("vpn", 8331), ("lan", 8728), ("vpn", 8331), ("lan", 8728), ("vpn", 8331)]
    assert closed == ["vpn", "lan", "vpn", "lan", "vpn"]
