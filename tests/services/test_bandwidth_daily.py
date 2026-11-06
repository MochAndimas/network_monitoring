"""Calendar allocation and transactional reporting invariants."""

from datetime import UTC, date, datetime
from ipaddress import IPv4Address, IPv4Network

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from backend.app.bandwidth.contracts import FlowPolicy
from backend.app.bandwidth.daily import DAY_NS, allocate_days
from backend.app.bandwidth.ingestion_config import IngestionPolicy
from backend.app.bandwidth.spool import source_manifest
from backend.app.models.bandwidth_daily import BandwidthDailyUsage
from backend.app.services.bandwidth_ingestion_service import ingest_segment
from backend.app.services.bandwidth_query_service import list_clients, query_usage
from tests.bandwidth_fixtures import record, sealed
from tests.test_utils import run


@pytest.fixture
def policy():
    return IngestionPolicy(
        FlowPolicy(1, frozenset({13}), frozenset({10}), (IPv4Network("192.168.1.0/24"),), ()), IPv4Address("192.0.2.1")
    )


MIDNIGHT = int(datetime(2026, 10, 14, 17, tzinfo=UTC).timestamp()) * 10**9


@pytest.mark.parametrize("count", [1, 2, 101, 2**53 + 7, 2**63 - 1])
def test_allocation_conserves_exact_bytes_at_wib_midnight(count):
    rows = list(allocate_days(MIDNIGHT - 10, MIDNIGHT + 20, count))
    assert rows == [(date(2026, 10, 14), count // 3, True), (date(2026, 10, 15), count - count // 3, True)]
    assert sum(value for _, value, _ in rows) == count


def test_half_open_interval_instant_and_multiday_rounding():
    assert list(allocate_days(MIDNIGHT - 10, MIDNIGHT, 9)) == [(date(2026, 10, 14), 9, False)]
    assert list(allocate_days(MIDNIGHT, MIDNIGHT, 9)) == [(date(2026, 10, 15), 9, False)]
    rows = list(allocate_days(MIDNIGHT, MIDNIGHT + 3 * DAY_NS, 2))
    assert [count for _, count, _ in rows] == [0, 1, 1]


def test_rollup_commit_replay_rollback_late_flow_and_queries(inventory_sessions, tmp_path, policy):
    source = source_manifest(tmp_path, router_id=1)
    payload = record(time_flow_start_ns=MIDNIGHT - 10, time_flow_end_ns=MIDNIGHT + 20, bytes=101)
    segment = sealed(tmp_path, payload)

    async def scenario():
        with pytest.raises(RuntimeError):
            async with inventory_sessions.begin() as db:
                await ingest_segment(db, source, segment, payload, policy)
                raise RuntimeError("rollback")
        async with inventory_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(BandwidthDailyUsage)) == 0
        async with inventory_sessions.begin() as db:
            await ingest_segment(db, source, segment, payload, policy)
        async with inventory_sessions.begin() as db:
            await ingest_segment(db, source, segment, payload, policy)
        # A new late segment updates the old days; replay of the first did not.
        async with inventory_sessions.begin() as db:
            await ingest_segment(db, source, sealed(tmp_path, payload), payload, policy)
        async with inventory_sessions() as db:
            page = await query_usage(db, 1, date(2026, 10, 14), date(2026, 10, 15))
            assert [row.total_bytes for row in page.items] == ["66", "136"]
            assert [row.estimated_bytes for row in page.items] == ["66", "136"]
            assert [row.unresolved_bytes for row in page.items] == ["66", "136"]
            top = await query_usage(db, 1, page.start, page.end, top=True)
            assert top.items[0].subject == "ip:192.168.1.31"
            assert top.items[0].total_bytes == "202"
            assert top.completeness == "unverified"
            assert (await query_usage(db, 2, page.start, page.end)).items == []

    run(scenario())


def test_top_pagination_and_client_identity_grouping(inventory_sessions):
    async def scenario():
        async with inventory_sessions.begin() as db:
            from backend.app.models.bandwidth import BandwidthClient

            db.add(
                BandwidthClient(
                    id=1,
                    router_id=1,
                    mac_address="02:00:00:00:00:01",
                    hostname="Laptop",
                    custom_name="Office",
                    first_seen_ns=1,
                    last_seen_ns=2,
                )
            )
            await db.flush()
            for day in (date(2026, 10, 14), date(2026, 10, 15)):
                db.add(
                    BandwidthDailyUsage(
                        router_id=1,
                        day=day,
                        subject="c:1",
                        client_id=1,
                        upload_bytes=100,
                        download_bytes=50,
                        estimated_bytes=0,
                        updated_ns=1,
                    )
                )
            db.add(
                BandwidthDailyUsage(
                    router_id=1,
                    day=day,
                    subject="ip:192.168.1.2",
                    unresolved_ip="192.168.1.2",
                    upload_bytes=300,
                    download_bytes=0,
                    estimated_bytes=0,
                    updated_ns=1,
                )
            )
        async with inventory_sessions() as db:
            page = await query_usage(db, 1, date(2026, 10, 14), day, top=True, limit=1)
            assert page.has_more and page.items[0].subject == "c:1"
            assert page.items[0].display_name == "Office"
            assert page.items[0].unresolved_bytes == "0"
            page = await query_usage(db, 1, page.start, day, top=True, limit=1, offset=1)
            assert not page.has_more and page.items[0].subject == "ip:192.168.1.2"

    run(scenario())


def test_database_counter_precision(inventory_sessions, tmp_path, policy):
    source = source_manifest(tmp_path, router_id=1)

    async def scenario():
        async with inventory_sessions() as db:
            mysql = db.get_bind().dialect.name == "mysql"
        # MySQL DECIMAL sums may exceed BIGINT; SQLite's test variant uses int64.
        count = 2**63 - 1 if mysql else 2**53 + 1
        payload = record(bytes=count, time_flow_start_ns=MIDNIGHT, time_flow_end_ns=MIDNIGHT + 10)
        for _ in range(2):
            async with inventory_sessions.begin() as db:
                await ingest_segment(db, source, sealed(tmp_path, payload), payload, policy)
        async with inventory_sessions() as db:
            page = await query_usage(db, 1, date(2026, 10, 15), date(2026, 10, 15), top=True)
            assert page.items[0].total_bytes == str(count * 2)

    run(scenario())


def test_long_download_spans_multiple_bounded_write_batches(inventory_sessions, tmp_path, policy):
    source = source_manifest(tmp_path, router_id=1)
    payload = record(
        in_if=10,
        out_if=13,
        post_nat_dst_addr="192.168.1.31",
        src_addr="1.1.1.1",
        time_flow_start_ns=MIDNIGHT,
        time_flow_end_ns=MIDNIGHT + 1001 * DAY_NS,
        bytes=1001,
    )

    async def scenario():
        async with inventory_sessions.begin() as db:
            await ingest_segment(db, source, sealed(tmp_path, payload), payload, policy)
        async with inventory_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(BandwidthDailyUsage)) == 1001
            assert await db.scalar(select(func.sum(BandwidthDailyUsage.download_bytes))) == 1001
            assert await db.scalar(select(func.sum(BandwidthDailyUsage.upload_bytes))) == 0
            assert await db.scalar(select(func.sum(BandwidthDailyUsage.estimated_bytes))) == 1001

    run(scenario())


def test_client_keyset_pagination_and_foreign_router_filter(inventory_sessions):
    from backend.app.models.bandwidth import BandwidthClient

    async def scenario():
        async with inventory_sessions.begin() as db:
            for identity, router_id in ((1, 1), (2, 2), (3, 1)):
                db.add(
                    BandwidthClient(
                        id=identity,
                        router_id=router_id,
                        mac_address=f"02:00:00:00:00:0{identity}",
                        first_seen_ns=1,
                        last_seen_ns=2,
                    )
                )
        async with inventory_sessions() as db:
            page = await list_clients(db, 1, 1, 0)
            assert [item.id for item in page.items] == [1]
            assert page.items[0].display_name == "02:00:00:00:00:01"
            page = await list_clients(db, 1, 1, page.next_after_id)
            assert [item.id for item in page.items] == [3] and page.next_after_id is None
            with pytest.raises(HTTPException) as error:
                await query_usage(db, 1, date(2026, 10, 15), date(2026, 10, 15), client_id=2)
            assert error.value.status_code == 404

    run(scenario())
