"""Standalone polling lifecycle; SQL commit always precedes spool acknowledgement."""

import asyncio
import logging
import math
from contextlib import suppress
from pathlib import Path
from time import perf_counter, time_ns

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..models.bandwidth_ingestion import BandwidthFlowStream
from ..repositories.bandwidth_flow_repository import BandwidthFlowRepository
from ..services.bandwidth_ingestion_service import IngestionReport, ingest_segment, pending_segment
from .ingestion_config import IngestionPolicy
from .profiling import IngestionProfiler, PhaseTimer
from .spool import SealedSegment, SpoolError, SpoolSource, source_manifest, spool_lock, sync_directory

logger = logging.getLogger(__name__)


async def ingest_once(
    sessions: async_sessionmaker[AsyncSession],
    directory: Path,
    source: SpoolSource,
    policy: IngestionPolicy,
    *,
    batch_size: int = 500,
    maximum_segment_bytes: int = 64 * 1024**2,
    timings: dict[str, float] | None = None,
    max_segments: int = 1,
    max_transaction_seconds: float = 10,
) -> IngestionReport | None:
    if not 1 <= max_segments <= 8 or not 1 <= batch_size <= 10000:
        raise ValueError("Invalid ingestion transaction limits")
    if not math.isfinite(max_transaction_seconds) or max_transaction_seconds <= 0:
        raise ValueError("Invalid transaction duration budget")
    timer = PhaseTimer(timings)
    if source.router_id != policy.flow.router_id:
        raise SpoolError("source_router_mismatch")
    completed: list[SealedSegment] = []
    accepted = rejected = payload_bytes = 0
    report = None
    async with sessions.begin() as db:
        stream = await BandwidthFlowRepository(db).lock_stream(
            source.stream_id, source.router_id, policy.digest, time_ns()
        )
        timer.mark("router_stream_lock_ms")
        pending = await pending_segment(db, source.stream_id)
        if pending is not None:
            segment = SealedSegment.from_path(directory / f"{pending.segment_id}.{pending.checksum}.ready")
            if not segment.path.exists():
                raise SpoolError("pending_segment_missing")
        else:
            segment = None
        paths = []
        for path in directory.glob("*.ready"):
            if segment is None or path != segment.path:
                paths.append(path)
            if len(paths) > 1024:
                raise SpoolError("too_many_segments")
        paths.sort(key=lambda path: (path.stat().st_mtime_ns, path.name))
        segments = ([segment] if segment is not None else []) + [
            SealedSegment.from_path(path) for path in paths[:max_segments]
        ]
        segments = segments[:max_segments]
        if not segments:
            stream.status, stream.last_error_code, stream.heartbeat_ns = "idle", None, time_ns()
            return None
        timer.mark("pending_lookup_ms")
        work_started = perf_counter()
        record_budget = min(batch_size * max_segments, 10000)
        for segment in segments:
            # Soft time/byte budget: finish the current atomic batch, then yield
            # the router mutex. One legacy segment may exceed the 16 MiB budget.
            if report is not None and (
                perf_counter() - work_started >= max_transaction_seconds
                or payload_bytes + segment.path.stat().st_size > 16 * 1024**2
            ):
                break
            payload = await asyncio.to_thread(segment.read_verified, maximum_segment_bytes)
            payload_bytes += len(payload)
            timer.mark("spool_read_verify_ms")
            report = await ingest_segment(
                db, source, segment, payload, policy,
                batch_size=record_budget - accepted - rejected, timings=timings,
            )
            accepted += report.accepted
            rejected += report.rejected
            timer.mark("segment_total_ms")
            if report.completed:
                completed.append(segment)
            if not report.completed or accepted + rejected >= record_budget:
                break
    timer.mark("commit_ms")
    # Commit succeeded. Cancellation or unlink failure here safely replays the
    # completed checkpoint on the next pass; it cannot insert records twice.
    if completed:
        await asyncio.to_thread(acknowledge_segments, directory, completed)
    timer.mark("acknowledge_ms")
    assert report is not None
    return IngestionReport(accepted, rejected, report.offset, report.completed)


def acknowledge_segments(directory: Path, segments: list[SealedSegment]) -> None:
    """All checkpoints are committed before unlink; one directory fsync per group.

    A crash or unlink/fsync error can leave committed files for safe replay.
    """
    try:
        for segment in segments:
            segment.path.unlink(missing_ok=True)
    finally:
        sync_directory(directory)


async def _record_error(
    sessions: async_sessionmaker[AsyncSession],
    source: SpoolSource,
    code: str,
) -> None:
    try:
        async with sessions.begin() as db:
            rows = await db.scalars(
                select(BandwidthFlowStream).where(BandwidthFlowStream.stream_id == source.stream_id).with_for_update()
            )
            stream = rows.one_or_none()
            if stream is not None:
                stream.status, stream.last_error_code, stream.heartbeat_ns = "error", code, time_ns()
    except SQLAlchemyError:
        # During an outage the last heartbeat becomes stale; never log a DB URL.
        logger.error("Flow ingestion cannot update its heartbeat")


async def run_worker(
    sessions: async_sessionmaker[AsyncSession],
    directory: Path,
    policy: IngestionPolicy,
    stop: asyncio.Event,
    *,
    batch_size: int = 500,
    poll_seconds: float = 1,
) -> None:
    if poll_seconds <= 0:
        raise ValueError("Poll interval must be positive")
    source = source_manifest(directory)
    if source.router_id != policy.flow.router_id:
        raise SpoolError("source_router_mismatch")
    failures = 0
    profiler = IngestionProfiler(source.router_id, logger)
    with spool_lock(directory, "worker"):
        while not stop.is_set():
            delay = poll_seconds
            timings: dict[str, float] = {}
            started = perf_counter()
            report = None
            failed = False
            try:
                report = await ingest_once(
                    sessions, directory, source, policy, batch_size=batch_size,
                    timings=timings, max_segments=4,
                )
                failures = 0
                if report is not None:
                    continue
            except SQLAlchemyError:
                failed = True
                failures += 1
                delay = min(poll_seconds * 2 ** min(failures, 5), 30)
                await _record_error(sessions, source, "database_error")
                logger.error("Flow database unavailable; checkpoint retained for retry")
            except SpoolError as error:
                failed = True
                await _record_error(sessions, source, str(error))
                raise
            except (OSError, ValueError):
                failed = True
                await _record_error(sessions, source, "spool_or_policy_error")
                raise
            finally:
                profiler.observe(timings, (perf_counter() - started) * 1000, report, failed)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=delay)
        await _record_error(sessions, source, "worker_stopped")
