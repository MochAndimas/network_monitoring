"""Identity history, isolation, replay and transaction rollback contracts."""

import asyncio
import os
from dataclasses import replace

import pytest
from sqlalchemy import func, select

from backend.app.bandwidth.discovery import InventoryMetricBatch, build_inventory_snapshot
from backend.app.models.bandwidth import BandwidthClient, BandwidthInventoryState, BandwidthIPHistory
from backend.app.models.device import Device
from backend.app.models.metric import Metric
from backend.app.monitors.mikrotik.parts import impl as mikrotik_impl
from backend.app.repositories.bandwidth_inventory_repository import BandwidthInventoryRepository
from backend.app.services import run_cycle_service
from backend.app.services.bandwidth_inventory_service import sync_inventory
from backend.app.services.monitoring_service import persist_metrics
from tests.test_utils import run

T0 = 1_800_000_000_000_000_000
SECOND = 10**9
MAC_A = "70:08:94:1B:9C:DF"
MAC_B = "70:08:94:1B:9C:E0"


def lease(mac=MAC_A, ip="192.168.1.31", hostname="laptop"):
    return {"address": ip, "mac-address": mac, "status": "bound", "host-name": hostname}


def snapshot(offset=0, rows=None, router=1, arp=()):
    return build_inventory_snapshot(router, T0 + offset * SECOND, [lease()] if rows is None else rows, arp)


def test_discovery_dhcp_precedence_and_conflicts():
    arp = [
        {"address": "192.168.1.31", "mac-address": MAC_A.lower(), "status": "reachable"},
        {"address": "192.168.1.32", "mac-address": MAC_B, "status": "permanent"},
    ]
    result = snapshot(arp=arp)
    assert [(item.ip, item.mac, item.source, item.hostname) for item in result.clients] == [
        ("192.168.1.31", MAC_A, "dhcp", "laptop"),
        ("192.168.1.32", MAC_B, "arp", None),
    ]
    result = snapshot(arp=[dict(arp[0], **{"mac-address": MAC_B})])
    assert not result.clients
    assert result.ambiguous_ips == ("192.168.1.31",)


def test_discovery_ignores_unbound_and_unreachable_rows_and_rejects_bad_identities():
    result = snapshot(
        rows=[
            dict(lease(), status="waiting"),
            lease(mac="FF:FF:FF:FF:FF:FF"),
            lease(mac="00:00:00:00:00:00"),
            lease(mac="invalid"),
            lease(ip="::1"),
        ],
        arp=[{"address": "192.168.1.31", "mac-address": MAC_A, "status": "stale"}],
    )
    assert not result.clients
    assert result.invalid_rows == 4


@pytest.mark.parametrize("router,observed", [(True, T0), (0, T0), (1, True), (1, 0), (1, 2**63 - 1)])
def test_discovery_rejects_bad_snapshot_coordinates(router, observed):
    with pytest.raises(ValueError):
        build_inventory_snapshot(router, observed, [], [])


def test_active_lease_fields_take_precedence():
    row = dict(
        lease(), **{"active-address": "192.168.1.40", "active-mac-address": MAC_B, "active-host-name": "actual-host"}
    )
    item = snapshot(rows=[row]).clients[0]
    assert (item.ip, item.mac, item.hostname) == ("192.168.1.40", MAC_B, "actual-host")


def test_replay_continuity_and_router_scope(inventory_sessions):
    async def scenario():
        async with inventory_sessions.begin() as db:
            assert await sync_inventory(db, snapshot())
            assert not await sync_inventory(db, snapshot())
            assert await sync_inventory(db, snapshot(60))
            assert not await sync_inventory(db, snapshot(30, rows=[lease(MAC_B)]))
            assert await sync_inventory(db, snapshot(router=2))
        async with inventory_sessions() as db:
            clients = list((await db.scalars(select(BandwidthClient).order_by(BandwidthClient.id))).all())
            assert len(clients) == 2
            assert clients[0].mac_address == clients[1].mac_address
            assert clients[0].router_id != clients[1].router_id
            assert await db.scalar(select(func.count()).select_from(Device)) == 2
            assert await db.scalar(select(func.count()).select_from(BandwidthIPHistory)) == 2
            repository = BandwidthInventoryRepository(db)
            assert await repository.resolve_client(1, "192.168.1.31", T0, T0 + 59 * SECOND) == clients[0].id
            assert await repository.resolve_client(1, "192.168.1.31", T0 - 1, T0) is None
            assert await repository.resolve_client(1, "192.168.1.31", T0, T0 + 61 * SECOND) is None

    run(scenario())


def test_ip_reassignment_and_long_gap_never_relabel_old_traffic(inventory_sessions):
    async def scenario():
        async with inventory_sessions.begin() as db:
            await sync_inventory(db, snapshot())
            await sync_inventory(db, snapshot(60))
            await sync_inventory(db, snapshot(120, rows=[lease(MAC_B)]))
            await sync_inventory(db, snapshot(180, rows=[lease(MAC_B)]))
            await sync_inventory(db, snapshot(400, rows=[lease(MAC_B)]))
        async with inventory_sessions() as db:
            rows = list((await db.scalars(select(BandwidthIPHistory).order_by(BandwidthIPHistory.id))).all())
            assert len(rows) == 3
            assert rows[0].ended_ns == T0 + 60 * SECOND + 1
            assert rows[1].ended_ns == T0 + 180 * SECOND + 1
            assert rows[2].active_slot == 1
            repository = BandwidthInventoryRepository(db)
            assert await repository.resolve_client(1, "192.168.1.31", T0, T0 + 60 * SECOND) == rows[0].client_id
            assert await repository.resolve_client(1, "192.168.1.31", T0 + 119 * SECOND, T0 + 121 * SECOND) is None
            assert await repository.resolve_client(1, "192.168.1.31", T0 + 200 * SECOND, T0 + 201 * SECOND) is None

    run(scenario())


def test_conflict_and_disappearance_close_only_at_last_observation(inventory_sessions):
    async def scenario():
        async with inventory_sessions.begin() as db:
            await sync_inventory(db, snapshot())
            await sync_inventory(db, snapshot(60, rows=[lease(), lease(MAC_B)]))
            state = await db.get(BandwidthInventoryState, 1)
            assert state.ambiguous_ip_count == 1
            await sync_inventory(db, snapshot(120))
            await sync_inventory(db, snapshot(180, rows=[]))
        async with inventory_sessions() as db:
            rows = list((await db.scalars(select(BandwidthIPHistory).order_by(BandwidthIPHistory.id))).all())
            assert [(item.last_observed_ns, item.ended_ns) for item in rows] == [
                (T0, T0 + 1),
                (T0 + 120 * SECOND, T0 + 120 * SECOND + 1),
            ]

    run(scenario())


def test_ip_change_keeps_manual_name_and_original_identity(inventory_sessions):
    async def scenario():
        async with inventory_sessions.begin() as db:
            await sync_inventory(db, snapshot())
            client = await db.scalar(select(BandwidthClient))
            client.custom_name = "Finance laptop"
            await sync_inventory(db, snapshot(60, rows=[lease(ip="192.168.1.45", hostname="")]))
        async with inventory_sessions() as db:
            client = await db.scalar(select(BandwidthClient))
            assert client.custom_name == "Finance laptop"
            assert client.hostname == "laptop"
            assert client.last_seen_ns == T0 + 60 * SECOND
            assert await db.scalar(select(func.count()).select_from(BandwidthClient)) == 1

    run(scenario())


def test_inventory_and_metrics_share_commit_and_rollback(inventory_sessions):
    async def scenario():
        batch = InventoryMetricBatch(
            [{"device_id": 1, "metric_name": "mikrotik_api", "metric_value": "ok", "status": "ok"}], (snapshot(),)
        )
        with pytest.raises(RuntimeError, match="rollback"):
            async with inventory_sessions.begin() as db:
                await persist_metrics(db, batch, commit=False)
                raise RuntimeError("rollback")
        async with inventory_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(BandwidthClient)) == 0
            assert await db.scalar(select(func.count()).select_from(Metric)) == 0
        async with inventory_sessions.begin() as db:
            await persist_metrics(db, batch, commit=False)
        async with inventory_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(BandwidthClient)) == 1
            assert await db.scalar(select(func.count()).select_from(Metric)) == 1

    run(scenario())


def test_inventory_only_batch_commits_when_requested(inventory_sessions):
    async def scenario():
        async with inventory_sessions() as db:
            await persist_metrics(db, InventoryMetricBatch([], (snapshot(),)))
        async with inventory_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(BandwidthClient)) == 1

    run(scenario())


def test_missing_router_is_rejected(inventory_sessions):
    async def scenario():
        async with inventory_sessions.begin() as db:
            with pytest.raises(ValueError, match="does not exist"):
                await sync_inventory(db, replace(snapshot(), router_id=999))

    run(scenario())


@pytest.mark.parametrize("enabled", [False, True])
def test_collector_feature_flag_controls_persistence_without_extra_api_reads(inventory_sessions, monkeypatch, enabled):
    calls = []

    class API:
        def path(self, *parts):
            calls.append(parts)
            return [lease()] if parts == ("ip", "dhcp-server", "lease") else []

        def close(self):
            pass

    async def no_ping(*args):
        return []

    for field, value in {
        "bandwidth_inventory_enabled": enabled,
        "mikrotik_targets": "",
        "ro_mikrotik_host": "",
        "mikrotik_host": "192.0.2.1",
        "mikrotik_username": "test",
        "mikrotik_password": "test",
        "mikrotik_dynamic_sections": "",
    }.items():
        monkeypatch.setattr(mikrotik_impl.settings, field, value)
    monkeypatch.setattr(mikrotik_impl, "connect", lambda **kwargs: API())
    monkeypatch.setattr(mikrotik_impl, "_build_ping_metrics", no_ping)

    async def scenario():
        async with inventory_sessions.begin() as db:
            batch = await mikrotik_impl.run_mikrotik_checks(db)
            assert isinstance(batch, InventoryMetricBatch) is enabled
            assert await db.scalar(select(func.count()).select_from(BandwidthClient)) == 0
            await persist_metrics(db, batch, commit=False)
        async with inventory_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(BandwidthClient)) == int(enabled)
        assert calls.count(("ip", "dhcp-server", "lease")) == 1
        assert calls.count(("ip", "arp")) == 1

    run(scenario())


@pytest.mark.parametrize("with_metrics", [True, False])
def test_manual_cycle_carries_inventory_from_temporary_collector_session(inventory_sessions, monkeypatch, with_metrics):
    async def runner(db):
        # Collector session ends before the write transaction begins.
        metrics = [{"device_id": 1, "metric_name": "mikrotik_api", "metric_value": "ok", "status": "ok"}]
        return InventoryMetricBatch(metrics if with_metrics else [], (snapshot(),))

    async def no_alerts(db, **kwargs):
        return []

    monkeypatch.setattr(run_cycle_service, "evaluate_alerts", no_alerts)

    async def scenario():
        async with inventory_sessions() as db:
            result = await run_cycle_service.run_monitoring_cycle(
                db, runners=(runner,), collector_sessions=inventory_sessions
            )
            assert result["metrics_collected"] == int(with_metrics)
        async with inventory_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(BandwidthClient)) == 1

    run(scenario())


@pytest.mark.skipif(not os.environ.get("BANDWIDTH_TEST_DATABASE_URL", "").startswith("mysql"), reason="MySQL row locks")
def test_concurrent_mysql_writers_see_current_inventory_after_router_lock(inventory_sessions):
    async def scenario():
        first_written = asyncio.Event()
        second_read = asyncio.Event()

        async def first_writer():
            async with inventory_sessions.begin() as db:
                await sync_inventory(db, snapshot())
                first_written.set()
                await second_read.wait()

        async def second_writer():
            await first_written.wait()
            async with inventory_sessions.begin() as db:
                # Establish an old REPEATABLE READ snapshot before acquiring the
                # router lock, as the existing collector metric reads would do.
                assert await db.scalar(select(func.count()).select_from(BandwidthClient)) == 0
                second_read.set()
                await sync_inventory(db, snapshot(60))

        await asyncio.wait_for(asyncio.gather(first_writer(), second_writer()), timeout=15)
        async with inventory_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(BandwidthClient)) == 1
            assert await db.scalar(select(func.count()).select_from(BandwidthIPHistory)) == 1
            state = await db.get(BandwidthInventoryState, 1)
            assert state.observed_ns == T0 + 60 * SECOND

    run(scenario())
