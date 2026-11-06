"""Delayed identities conserve bytes, require evidence, and survive retries."""

import asyncio
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv4Network

import pytest
from sqlalchemy import func, select, update

from backend.app.bandwidth.contracts import FlowPolicy
from backend.app.bandwidth.discovery import ClientObservation, InventorySnapshot
from backend.app.bandwidth.ingestion_config import IngestionPolicy
from backend.app.bandwidth.spool import source_manifest
from backend.app.models.bandwidth import BandwidthClient, BandwidthIPHistory
from backend.app.models.bandwidth_daily import BandwidthDailyUsage as Daily
from backend.app.models.bandwidth_ingestion import BandwidthFlow as Flow
from backend.app.services.bandwidth_ingestion_service import ingest_segment
from backend.app.services.bandwidth_inventory_service import sync_inventory
from backend.app.services.bandwidth_query_service import query_usage
from backend.app.services.bandwidth_reconciliation_service import reconcile_identities
from backend.app.services.bandwidth_reconciliation_service import ReconciliationCursor
from tests.bandwidth_fixtures import record, sealed
from tests.test_utils import run

MIDNIGHT = int(datetime(2026, 10, 14, 17, tzinfo=UTC).timestamp()) * 10**9
CLIENT = ClientObservation("192.168.1.31", "02:00:00:00:00:01", "Laptop", "dhcp")


def test_cursor_passes_unresolvable_prefix_and_wraps_for_late_evidence(inventory_sessions, tmp_path):
    source = source_manifest(tmp_path, router_id=1)
    policy = IngestionPolicy(
        FlowPolicy(1, frozenset({13}), frozenset({10}), (IPv4Network("192.168.1.0/24"),), ()),
        IPv4Address("192.0.2.1"),
    )
    cursor = ReconciliationCursor()

    async def scenario():
        payload = record(time_flow_start_ns=MIDNIGHT - 100, time_flow_end_ns=MIDNIGHT - 90) * 11
        payload += record(time_flow_start_ns=MIDNIGHT, time_flow_end_ns=MIDNIGHT + 10)
        async with inventory_sessions.begin() as db:
            await ingest_segment(db, source, sealed(tmp_path, payload), payload, policy)
            await sync_inventory(db, InventorySnapshot(1, MIDNIGHT - 1, (CLIENT,), (), 0))
            await sync_inventory(db, InventorySnapshot(1, MIDNIGHT + 11, (CLIENT,), (), 0))
        for expected in (0, 0, 1):
            async with inventory_sessions.begin() as db:
                assert await reconcile_identities(db, 1, batch_size=5, cursor=cursor) == expected
        assert cursor == ReconciliationCursor()
        async with inventory_sessions.begin() as db:
            await db.execute(update(BandwidthIPHistory).values(first_observed_ns=MIDNIGHT - 101))
        async with inventory_sessions.begin() as db:
            assert await reconcile_identities(db, 1, batch_size=5, cursor=cursor) == 5
        # A fresh process may safely restart its bounded pass from zero.
        async with inventory_sessions.begin() as db:
            assert await reconcile_identities(db, 1, batch_size=5, cursor=ReconciliationCursor()) == 5

    run(scenario())


@pytest.mark.parametrize("invalidate_history", [False, True])
def test_discovery_does_not_lock_scan_and_rechecks_history(
    inventory_sessions, tmp_path, monkeypatch, invalidate_history,
):
    from sqlalchemy.dialects import mysql
    from sqlalchemy.ext.asyncio import AsyncSession
    from backend.app.repositories.bandwidth_inventory_repository import BandwidthInventoryRepository

    source = source_manifest(tmp_path, router_id=1)
    policy = IngestionPolicy(
        FlowPolicy(1, frozenset({13}), frozenset({10}), (IPv4Network("192.168.1.0/24"),), ()),
        IPv4Address("192.0.2.1"),
    )
    statements = []
    original_execute = AsyncSession.execute
    original_lock = BandwidthInventoryRepository.lock_router

    async def capture(self, statement, *args, **kwargs):
        statements.append(statement)
        return await original_execute(self, statement, *args, **kwargs)

    async def lock(self, router_id):
        await original_lock(self, router_id)
        if invalidate_history:
            await self.db.execute(update(BandwidthIPHistory).values(last_observed_ns=MIDNIGHT - 1))

    async def scenario():
        payload = record(time_flow_start_ns=MIDNIGHT, time_flow_end_ns=MIDNIGHT + 10)
        async with inventory_sessions.begin() as db:
            await ingest_segment(db, source, sealed(tmp_path, payload), payload, policy)
            await sync_inventory(db, InventorySnapshot(1, MIDNIGHT - 2, (CLIENT,), (), 0))
            await sync_inventory(db, InventorySnapshot(1, MIDNIGHT + 12, (CLIENT,), (), 0))
        monkeypatch.setattr(AsyncSession, "execute", capture)
        monkeypatch.setattr(BandwidthInventoryRepository, "lock_router", lock)
        async with inventory_sessions.begin() as db:
            assert await reconcile_identities(db, 1) == (0 if invalidate_history else 1)

    run(scenario())
    sql = [str(stmt.compile(dialect=mysql.dialect())) for stmt in statements if getattr(stmt, "is_select", False)]
    assert "FOR UPDATE" not in sql[0]
    assert "bandwidth_flows" in sql[0]
    discovery = next(query for query in sql if "bandwidth_flows.id >" in query)
    assert "bandwidth_client_ip_history" not in discovery
    assert "FOR UPDATE" not in discovery
    assert "bandwidth_flows.id <=" in discovery
    flow_locks = [query for query in sql if "FROM bandwidth_flows" in query and "FOR UPDATE" in query]
    assert len(flow_locks) == 1
    assert "FORCE INDEX (PRIMARY)" in flow_locks[0]
    assert "bandwidth_flows.id IN" in flow_locks[0]
    assert "SELECT count" not in flow_locks[0]


def test_delayed_identity_moves_daily_bytes_once_with_rollback_and_batching(inventory_sessions, tmp_path):
    source = source_manifest(tmp_path, router_id=1)
    policy = IngestionPolicy(
        FlowPolicy(1, frozenset({13}), frozenset({10}), (IPv4Network("192.168.1.0/24"),), ()),
        IPv4Address("192.0.2.1"),
    )
    payload = record(time_flow_start_ns=MIDNIGHT - 10, time_flow_end_ns=MIDNIGHT + 20, bytes=101)
    payload += record(
        src_addr="142.251.10.95",
        dst_addr="103.113.78.150",
        post_nat_dst_addr="c0a8011f",
        in_if=10,
        out_if=13,
        time_flow_start_ns=MIDNIGHT - 5,
        time_flow_end_ns=MIDNIGHT + 25,
        bytes=203,
    )
    # Before the first observation must never acquire today's identity.
    payload += record(time_flow_start_ns=MIDNIGHT - 100, time_flow_end_ns=MIDNIGHT - 90, bytes=7)
    segment = sealed(tmp_path, payload)

    async def totals():
        async with inventory_sessions() as db:
            rows = (await db.execute(select(Daily).order_by(Daily.day, Daily.subject))).scalars().all()
            return tuple(
                sum(int(getattr(r, column)) for r in rows)
                for column in ("upload_bytes", "download_bytes", "estimated_bytes")
            )

    async def scenario():
        async with inventory_sessions.begin() as db:
            await sync_inventory(db, InventorySnapshot(1, MIDNIGHT - 20, (CLIENT,), (), 0))
            await ingest_segment(db, source, segment, payload, policy)
            assert await reconcile_identities(db, 1) == 0
        before = await totals()
        async with inventory_sessions.begin() as db:
            await sync_inventory(db, InventorySnapshot(1, MIDNIGHT + 30, (CLIENT,), (), 0))
        with pytest.raises(RuntimeError):
            async with inventory_sessions.begin() as db:
                assert await reconcile_identities(db, 1) == 2
                raise RuntimeError("rollback")
        assert await totals() == before
        async with inventory_sessions.begin() as db:
            assert await reconcile_identities(db, 2) == 0
            assert await reconcile_identities(db, 1, batch_size=1) == 1
        async with inventory_sessions.begin() as db:
            assert await reconcile_identities(db, 1) == 1
            assert await reconcile_identities(db, 1) == 0
            await ingest_segment(db, source, segment, payload, policy)
        assert await totals() == before == (108, 203, 304)
        async with inventory_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Flow).where(Flow.client_id.is_not(None))) == 2
            unresolved = list(await db.scalars(select(Daily).where(Daily.client_id.is_(None))))
            assert len(unresolved) == 1
            assert int(unresolved[0].upload_bytes) == 7
            page = await query_usage(db, 1, unresolved[0].day, unresolved[0].day, top=True)
            legacy = next(row for row in page.items if row.client_id is None)
            assert legacy.latest_observation.display_name == "Laptop"
            assert legacy.latest_observation.mac_address == CLIENT.mac
            assert legacy.unresolved_bytes == "7"
            assert legacy.subject == f"ip:{CLIENT.ip}"

    run(scenario())


def test_gaps_changed_owners_and_ambiguous_intervals_are_never_guessed(inventory_sessions, tmp_path):
    source = source_manifest(tmp_path, router_id=1)
    policy = IngestionPolicy(
        FlowPolicy(1, frozenset({13}), frozenset({10}), (IPv4Network("192.168.1.0/24"),), ()),
        IPv4Address("192.0.2.1"),
    )
    payload = record(time_flow_start_ns=MIDNIGHT, time_flow_end_ns=MIDNIGHT + 10)

    async def scenario():
        async with inventory_sessions.begin() as db:
            await ingest_segment(db, source, sealed(tmp_path, payload), payload, policy)
            db.add(BandwidthClient(id=10, router_id=1, mac_address=CLIENT.mac, first_seen_ns=1, last_seen_ns=2))
            db.add(
                BandwidthClient(id=11, router_id=1, mac_address="02:00:00:00:00:02", first_seen_ns=1, last_seen_ns=2)
            )
            await db.flush()
            db.add_all(
                [
                    BandwidthIPHistory(
                        router_id=1,
                        client_id=10,
                        ip_address=CLIENT.ip,
                        source="dhcp",
                        first_observed_ns=MIDNIGHT - 10,
                        last_observed_ns=MIDNIGHT + 4,
                        ended_ns=MIDNIGHT + 5,
                    ),
                    BandwidthIPHistory(
                        router_id=1,
                        client_id=11,
                        ip_address=CLIENT.ip,
                        source="dhcp",
                        first_observed_ns=MIDNIGHT + 5,
                        last_observed_ns=MIDNIGHT + 20,
                        ended_ns=MIDNIGHT + 21,
                    ),
                ]
            )
        async with inventory_sessions.begin() as db:
            assert await reconcile_identities(db, 1) == 0
            # Even contradictory full coverage is rejected, not MIN(client_id).
            await db.execute(
                update(BandwidthIPHistory).values(first_observed_ns=MIDNIGHT - 10, last_observed_ns=MIDNIGHT + 20)
            )
        async with inventory_sessions.begin() as db:
            assert await reconcile_identities(db, 1) == 0

    run(scenario())


def test_missing_daily_source_rolls_back_identity(inventory_sessions, tmp_path):
    from sqlalchemy import delete

    source = source_manifest(tmp_path, router_id=1)
    policy = IngestionPolicy(
        FlowPolicy(1, frozenset({13}), frozenset({10}), (IPv4Network("192.168.1.0/24"),), ()),
        IPv4Address("192.0.2.1"),
    )
    payload = record(time_flow_start_ns=MIDNIGHT, time_flow_end_ns=MIDNIGHT + 10)

    async def scenario():
        async with inventory_sessions.begin() as db:
            await ingest_segment(db, source, sealed(tmp_path, payload), payload, policy)
            await sync_inventory(db, InventorySnapshot(1, MIDNIGHT - 1, (CLIENT,), (), 0))
            await sync_inventory(db, InventorySnapshot(1, MIDNIGHT + 11, (CLIENT,), (), 0))
            await db.execute(delete(Daily))
        with pytest.raises(ValueError, match="daily_source_mismatch"):
            async with inventory_sessions.begin() as db:
                await reconcile_identities(db, 1)
        async with inventory_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Flow).where(Flow.client_id.is_not(None))) == 0

    run(scenario())


def test_concurrent_mysql_reconciliation_moves_bytes_once(inventory_sessions, tmp_path):
    if inventory_sessions.kw["bind"].dialect.name != "mysql":
        pytest.skip("MySQL row locks required")
    source = source_manifest(tmp_path, router_id=1)
    policy = IngestionPolicy(
        FlowPolicy(1, frozenset({13}), frozenset({10}), (IPv4Network("192.168.1.0/24"),), ()),
        IPv4Address("192.0.2.1"),
    )
    payload = record(time_flow_start_ns=MIDNIGHT, time_flow_end_ns=MIDNIGHT + 10)

    async def reconcile():
        async with inventory_sessions.begin() as db:
            return await reconcile_identities(db, 1)

    async def scenario():
        async with inventory_sessions.begin() as db:
            await ingest_segment(db, source, sealed(tmp_path, payload), payload, policy)
            await sync_inventory(db, InventorySnapshot(1, MIDNIGHT - 1, (CLIENT,), (), 0))
            await sync_inventory(db, InventorySnapshot(1, MIDNIGHT + 11, (CLIENT,), (), 0))
        assert sorted(await asyncio.gather(reconcile(), reconcile())) == [0, 1]
        async with inventory_sessions() as db:
            rows = list(await db.scalars(select(Daily)))
            assert len(rows) == 1 and rows[0].client_id is not None
            assert int(rows[0].upload_bytes) == 4178

    run(scenario())
