"""Transaction/replay invariants across spool, classifier, identity and storage."""

import asyncio
import os
from dataclasses import replace
from ipaddress import IPv4Address, IPv4Network

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from backend.app.bandwidth import ingestion_runtime
from backend.app.bandwidth.contracts import FlowPolicy
from backend.app.bandwidth.discovery import build_inventory_snapshot
from backend.app.bandwidth.ingestion_config import IngestionPolicy
from backend.app.bandwidth.ingestion_runtime import ingest_once, run_worker
from backend.app.bandwidth.spool import SpoolError, source_manifest
from backend.app.models.bandwidth_ingestion import (
    BandwidthFlow,
    BandwidthFlowRejection,
    BandwidthFlowSegment,
    BandwidthFlowStream,
)
from backend.app.services.bandwidth_ingestion_service import ingest_segment
from backend.app.services.bandwidth_inventory_service import sync_inventory
from tests.bandwidth_fixtures import START, record, sealed
from tests.test_utils import run


def test_pending_checkpoint_mysql_query_uses_pending_index_and_equality():
    from sqlalchemy.dialects import mysql
    from backend.app.services.bandwidth_ingestion_service import pending_segment

    statements = []

    class Rows:
        def one_or_none(self):
            return None

    class DB:
        async def scalars(self, statement):
            statements.append(str(statement.compile(dialect=mysql.dialect())))
            return Rows()

    assert run(pending_segment(DB(), "fixture-stream")) is None
    query = statements[0]
    assert "FORCE INDEX (ix_bw_segment_pending)" in query
    assert "completed = false" in query
    assert "IS false" not in query
    assert "FOR UPDATE" in query


def test_ingestion_profile_reports_slow_identity_phase_after_commit(inventory_sessions, tmp_path, policy, monkeypatch):
    from backend.app.repositories.bandwidth_flow_repository import BandwidthFlowRepository

    original = BandwidthFlowRepository.resolve_clients

    async def slow(self, flows):
        await asyncio.sleep(0.02)
        return await original(self, flows)

    monkeypatch.setattr(BandwidthFlowRepository, "resolve_clients", slow)
    source = source_manifest(tmp_path, router_id=1)
    segment = sealed(tmp_path, record())
    timings = {}
    report = run(ingest_once(inventory_sessions, tmp_path, source, policy, timings=timings))
    assert report.accepted == 1 and report.completed
    assert not segment.path.exists()
    assert timings["resolve_clients_ms"] >= 15
    assert set(timings) == {
        "router_stream_lock_ms", "pending_lookup_ms", "spool_read_verify_ms",
        "segment_lock_ms", "checkpoint_load_ms", "parse_classify_ms",
        "resolve_clients_ms", "insert_flows_ms", "daily_aggregate_ms",
        "checkpoint_rejections_flush_ms", "segment_total_ms", "commit_ms", "acknowledge_ms",
    }
    assert all(value >= 0 for value in timings.values())


@pytest.fixture
def policy():
    return IngestionPolicy(
        FlowPolicy(
            1,
            frozenset({13}),
            frozenset({10}),
            (IPv4Network("192.168.1.0/24"),),
            (),
        ),
        IPv4Address("192.0.2.1"),
    )


def test_group_commits_once_before_one_directory_sync(inventory_sessions, tmp_path, policy, monkeypatch):
    from sqlalchemy import event

    source = source_manifest(tmp_path, router_id=1)
    segments = [sealed(tmp_path, record()) for _ in range(4)]
    commits, syncs = [], []
    engine = inventory_sessions.kw["bind"]

    def before_commit(connection):
        assert all(segment.path.exists() for segment in segments)
        commits.append(True)

    original_sync = ingestion_runtime.sync_directory

    def sync(directory):
        assert commits == [True]
        assert not list(tmp_path.glob("*.ready"))
        syncs.append(True)
        original_sync(directory)

    event.listen(engine.sync_engine, "commit", before_commit)
    monkeypatch.setattr(ingestion_runtime, "sync_directory", sync)
    try:
        report = run(ingest_once(inventory_sessions, tmp_path, source, policy, max_segments=4))
    finally:
        event.remove(engine.sync_engine, "commit", before_commit)
    assert report.accepted == 4
    assert commits == syncs == [True]


def test_group_rollback_preserves_all_files_and_retries_once(inventory_sessions, tmp_path, policy, monkeypatch):
    source = source_manifest(tmp_path, router_id=1)
    segments = [sealed(tmp_path, record()) for _ in range(4)]
    original = ingestion_runtime.ingest_segment
    calls = 0

    async def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SQLAlchemyError("fixture rollback")
        return await original(*args, **kwargs)

    async def scenario():
        monkeypatch.setattr(ingestion_runtime, "ingest_segment", fail_second)
        with pytest.raises(SQLAlchemyError):
            await ingest_once(inventory_sessions, tmp_path, source, policy, max_segments=4)
        assert all(segment.path.exists() for segment in segments)
        async with inventory_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(BandwidthFlow)) == 0
        monkeypatch.setattr(ingestion_runtime, "ingest_segment", original)
        report = await ingest_once(inventory_sessions, tmp_path, source, policy, max_segments=4)
        assert report.accepted == 4
        async with inventory_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(BandwidthFlow)) == 4

    run(scenario())


def test_group_partial_ack_replays_committed_files_without_duplicates(inventory_sessions, tmp_path, policy, monkeypatch):
    source = source_manifest(tmp_path, router_id=1)
    for _ in range(4):
        sealed(tmp_path, record())
    original = ingestion_runtime.acknowledge_segments

    def fail_partial(directory, segments):
        segments[0].path.unlink()
        raise OSError("fixture partial acknowledgement")

    async def scenario():
        monkeypatch.setattr(ingestion_runtime, "acknowledge_segments", fail_partial)
        with pytest.raises(OSError):
            await ingest_once(inventory_sessions, tmp_path, source, policy, max_segments=4)
        assert len(list(tmp_path.glob("*.ready"))) == 3
        monkeypatch.setattr(ingestion_runtime, "acknowledge_segments", original)
        report = await ingest_once(inventory_sessions, tmp_path, source, policy, max_segments=4)
        assert report.accepted == 0 and report.completed
        assert not list(tmp_path.glob("*.ready"))
        async with inventory_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(BandwidthFlow)) == 4

    run(scenario())


def test_group_record_budget_preserves_partial_checkpoint(inventory_sessions, tmp_path, policy):
    source = source_manifest(tmp_path, router_id=1)
    segment = sealed(tmp_path, record() * 6)

    async def scenario():
        report = await ingest_once(inventory_sessions, tmp_path, source, policy, batch_size=1, max_segments=4)
        assert report.accepted == 4 and not report.completed
        assert segment.path.exists()
        report = await ingest_once(inventory_sessions, tmp_path, source, policy, batch_size=1, max_segments=4)
        assert report.accepted == 2 and report.completed
        assert not segment.path.exists()

    run(scenario())


def test_group_yields_after_soft_duration_budget(inventory_sessions, tmp_path, policy, monkeypatch):
    source = source_manifest(tmp_path, router_id=1)
    for _ in range(4):
        sealed(tmp_path, record())
    clock = iter([0.0, 11.0])
    monkeypatch.setattr(ingestion_runtime, "perf_counter", lambda: next(clock))
    report = run(ingest_once(inventory_sessions, tmp_path, source, policy, max_segments=4))
    assert report.accepted == 1
    assert len(list(tmp_path.glob("*.ready"))) == 3


def test_oldest_segment_is_consumed_before_lower_uuid(inventory_sessions, tmp_path, policy):
    source = source_manifest(tmp_path, router_id=1)
    older = sealed(tmp_path, record(), identity="f" * 32)
    newer = sealed(tmp_path, record(), identity="0" * 32)
    os.utime(older.path, ns=(1_000_000_000, 1_000_000_000))
    os.utime(newer.path, ns=(2_000_000_000, 2_000_000_000))
    run(ingest_once(inventory_sessions, tmp_path, source, policy))
    assert not older.path.exists()
    assert newer.path.exists()


def test_replay_and_restart_resume_at_committed_offset(inventory_sessions, tmp_path, policy):
    source = source_manifest(tmp_path, router_id=1)
    payload = record() + b"not-json\n" + record()
    segment = sealed(tmp_path, payload)

    async def scenario():
        async with inventory_sessions.begin() as db:
            report = await ingest_segment(db, source, segment, payload, policy, batch_size=1)
            assert (report.accepted, report.offset, report.completed) == (1, len(record()), False)
        # Fresh session models a restart; checkpoint and rejection counters advance together.
        async with inventory_sessions.begin() as db:
            report = await ingest_segment(db, source, segment, payload, policy)
            assert (report.accepted, report.rejected, report.completed) == (1, 1, True)
        async with inventory_sessions.begin() as db:
            report = await ingest_segment(db, source, segment, payload, policy)
            assert report.accepted == report.rejected == 0
        async with inventory_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(BandwidthFlow)) == 2
            assert await db.scalar(select(func.sum(BandwidthFlow.byte_count))) == 8356
            rejection = await db.get(BandwidthFlowRejection, (source.stream_id, "invalid_json"))
            assert rejection.record_count == 1
            # Byte-identical records at different offsets are deliberately distinct.
            assert await db.scalar(select(func.count(func.distinct(BandwidthFlow.record_offset)))) == 2

    run(scenario())


def test_rollback_preserves_spool_and_checkpoint_for_retry(inventory_sessions, tmp_path, policy):
    source = source_manifest(tmp_path, router_id=1)
    payload = record() + b"bad-json\n"
    segment = sealed(tmp_path, payload)

    async def scenario():
        with pytest.raises(RuntimeError, match="crash"):
            async with inventory_sessions.begin() as db:
                await ingest_segment(db, source, segment, payload, policy)
                raise RuntimeError("crash before commit")
        assert segment.path.exists()
        async with inventory_sessions() as db:
            for model in (BandwidthFlow, BandwidthFlowSegment, BandwidthFlowRejection, BandwidthFlowStream):
                assert await db.scalar(select(func.count()).select_from(model)) == 0
        report = await ingest_once(inventory_sessions, tmp_path, source, policy)
        assert report.accepted == report.rejected == 1
        assert not segment.path.exists()

    run(scenario())


def test_crash_after_commit_before_unlink_is_idempotent(inventory_sessions, tmp_path, policy, monkeypatch):
    source = source_manifest(tmp_path, router_id=1)
    segment = sealed(tmp_path, record())
    original = ingestion_runtime.acknowledge_segments

    def fail_cleanup(*args):
        raise OSError("simulate crash after commit")

    async def scenario():
        monkeypatch.setattr(ingestion_runtime, "acknowledge_segments", fail_cleanup)
        with pytest.raises(OSError):
            await ingest_once(inventory_sessions, tmp_path, source, policy)
        assert segment.path.exists()
        monkeypatch.setattr(ingestion_runtime, "acknowledge_segments", original)
        report = await ingest_once(inventory_sessions, tmp_path, source, policy)
        assert report.completed and report.accepted == 0
        async with inventory_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(BandwidthFlow)) == 1
        assert not segment.path.exists()

    run(scenario())


def test_invalid_records_are_reason_counted_without_storing_raw_data(inventory_sessions, tmp_path, policy):
    source = source_manifest(tmp_path, router_id=1)
    payload = (
        record(sampler_address="192.0.2.2")
        + record(bytes=-1)
        + record(in_if=0)
        + b'{"a":1,"a":2}\n'
        + b"\xff\n"
        + b"partial"
    )
    sealed(tmp_path, payload)

    async def scenario():
        report = await ingest_once(inventory_sessions, tmp_path, source, policy)
        assert (report.accepted, report.rejected) == (0, 6)
        async with inventory_sessions() as db:
            counters = dict(
                (await db.execute(select(BandwidthFlowRejection.reason, BandwidthFlowRejection.record_count))).all()
            )
            assert counters == {
                "unexpected_exporter": 1,
                "invalid_integer": 1,
                "unclassified_interface": 1,
                "invalid_json": 2,
                "incomplete_record": 1,
            }

    run(scenario())


def test_identity_requires_full_historical_coverage(inventory_sessions, tmp_path, policy):
    source = source_manifest(tmp_path, router_id=1)
    rows = [{"address": "192.168.1.31", "mac-address": "70:08:94:1B:9C:DF", "status": "bound"}]
    payload = record() + record(time_flow_start_ns=START - 10)
    sealed(tmp_path, payload)

    async def scenario():
        async with inventory_sessions.begin() as db:
            await sync_inventory(db, build_inventory_snapshot(1, START, rows, []))
            await sync_inventory(db, build_inventory_snapshot(1, START + 100, rows, []))
        await ingest_once(inventory_sessions, tmp_path, source, policy)
        async with inventory_sessions() as db:
            flows = list((await db.scalars(select(BandwidthFlow).order_by(BandwidthFlow.id))).all())
            assert flows[0].client_id is not None
            assert flows[1].client_id is None
            assert flows[1].byte_count == 4178

    run(scenario())


def test_mutation_policy_change_and_missing_pending_file_fail_closed(inventory_sessions, tmp_path, policy):
    source = source_manifest(tmp_path, router_id=1)
    payload = record() * 2
    segment = sealed(tmp_path, payload)

    async def scenario():
        await ingest_once(inventory_sessions, tmp_path, source, policy, batch_size=1)
        async with inventory_sessions.begin() as db:
            with pytest.raises(ValueError, match="policy_changed"):
                await ingest_segment(db, source, segment, payload, replace(policy, exporter=IPv4Address("192.0.2.9")))
        segment.path.write_bytes(b"tampered")
        with pytest.raises(SpoolError, match="checksum"):
            await ingest_once(inventory_sessions, tmp_path, source, policy)
        segment.path.unlink()
        with pytest.raises(SpoolError, match="pending_segment_missing"):
            await ingest_once(inventory_sessions, tmp_path, source, policy)
        async with inventory_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(BandwidthFlow)) == 1

    run(scenario())


def test_worker_records_filesystem_error_in_heartbeat(inventory_sessions, tmp_path, policy):
    source = source_manifest(tmp_path, router_id=1)
    segment = sealed(tmp_path, record() * 2)

    async def scenario():
        await ingest_once(inventory_sessions, tmp_path, source, policy, batch_size=1)
        segment.path.unlink()
        with pytest.raises(SpoolError):
            await run_worker(inventory_sessions, tmp_path, policy, asyncio.Event())
        async with inventory_sessions() as db:
            stream = await db.get(BandwidthFlowStream, source.stream_id)
            assert stream.status == "error"
            assert stream.last_error_code == "pending_segment_missing"

    run(scenario())


def test_idle_stream_still_validates_router_binding_before_registration(inventory_sessions, tmp_path, policy):
    source = source_manifest(tmp_path, router_id=2)

    async def scenario():
        with pytest.raises(SpoolError, match="router_mismatch"):
            await ingest_once(inventory_sessions, tmp_path, source, policy)
        async with inventory_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(BandwidthFlowStream)) == 0

    run(scenario())


def test_worker_retries_database_failure_without_acknowledging_spool(inventory_sessions, tmp_path, policy, monkeypatch):
    source_manifest(tmp_path, router_id=1)
    segment = sealed(tmp_path, record())
    stop = asyncio.Event()
    calls = 0

    async def transient_failure(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            assert segment.path.exists()
            raise SQLAlchemyError("fixture database outage")
        assert segment.path.exists()
        result = await ingest_once(*args, **kwargs)
        stop.set()
        return result

    monkeypatch.setattr(ingestion_runtime, "ingest_once", transient_failure)
    run(run_worker(inventory_sessions, tmp_path, policy, stop, poll_seconds=0.01))
    assert calls == 2
    assert not segment.path.exists()


def test_large_batch_remains_bounded_and_keeps_precise_integer_counts(inventory_sessions, tmp_path, policy):
    source = source_manifest(tmp_path, router_id=1)
    payload = record(bytes=9_007_199_254_740_993) * 501
    segment = sealed(tmp_path, payload)

    async def scenario():
        first = await ingest_once(inventory_sessions, tmp_path, source, policy, batch_size=500)
        assert first.accepted == 500 and not first.completed and segment.path.exists()
        second = await ingest_once(inventory_sessions, tmp_path, source, policy, batch_size=500)
        assert second.accepted == 1 and second.completed
        async with inventory_sessions() as db:
            # Avoid SUM overflow on BIGINT: inspect individual byte counters.
            assert await db.scalar(select(func.count()).select_from(BandwidthFlow)) == 501
            assert await db.scalar(select(BandwidthFlow.byte_count).limit(1)) == 9_007_199_254_740_993

    run(scenario())


@pytest.mark.skipif(not os.environ.get("BANDWIDTH_TEST_DATABASE_URL", "").startswith("mysql"), reason="MySQL row locks")
def test_concurrent_mysql_replay_is_serialized(inventory_sessions, tmp_path, policy):
    source = source_manifest(tmp_path, router_id=1)
    payload = record() * 2
    segment = sealed(tmp_path, payload)

    async def scenario():
        first_written = asyncio.Event()
        old_snapshot = asyncio.Event()

        async def first():
            async with inventory_sessions.begin() as db:
                await ingest_segment(db, source, segment, payload, policy, batch_size=1)
                first_written.set()
                await old_snapshot.wait()

        async def second():
            await first_written.wait()
            async with inventory_sessions.begin() as db:
                assert await db.scalar(select(func.count()).select_from(BandwidthFlow)) == 0
                old_snapshot.set()
                report = await ingest_segment(db, source, segment, payload, policy)
                assert report.accepted == 1

        await asyncio.wait_for(asyncio.gather(first(), second()), timeout=15)
        async with inventory_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(BandwidthFlow)) == 2

    run(scenario())
