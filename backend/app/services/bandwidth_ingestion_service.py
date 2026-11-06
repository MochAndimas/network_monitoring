"""Commit flow records, rejection counters and byte checkpoint in one transaction."""

import hashlib
from collections import Counter
from dataclasses import dataclass
from io import BytesIO
from time import time_ns

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..bandwidth.classifier import classify_flow
from ..bandwidth.contracts import ClassifiedFlow, FlowRejected
from ..bandwidth.ingestion_config import IngestionPolicy, strict_json
from ..bandwidth.normalizer import normalize_flow
from ..bandwidth.profiling import PhaseTimer
from ..bandwidth.spool import SealedSegment, SpoolError, SpoolSource
from ..models.bandwidth_ingestion import BandwidthFlow, BandwidthFlowRejection, BandwidthFlowSegment
from ..repositories.bandwidth_daily_repository import increment_daily_usage
from ..repositories.bandwidth_flow_repository import BandwidthFlowRepository


@dataclass(frozen=True, slots=True)
class IngestionReport:
    accepted: int
    rejected: int
    offset: int
    completed: bool


def _parse(line: bytes, policy: IngestionPolicy, max_line_bytes: int) -> ClassifiedFlow:
    if len(line) > max_line_bytes:
        raise SpoolError("oversized_record")
    if not line.endswith(b"\n"):
        raise SpoolError("incomplete_record")
    try:
        record = strict_json(line)
    except (ValueError, UnicodeError, RecursionError):
        raise SpoolError("invalid_json") from None
    if not isinstance(record, dict):
        raise SpoolError("invalid_record")
    # Exporter identity is retained by the mapping, never inferred from client IP.
    if not policy.accepts_exporter(record.get("sampler_address")):
        raise SpoolError("unexpected_exporter")
    return classify_flow(normalize_flow(record), policy.flow)


async def ingest_segment(
    db: AsyncSession,
    source: SpoolSource,
    segment: SealedSegment,
    payload: bytes,
    policy: IngestionPolicy,
    *,
    batch_size: int = 500,
    max_line_bytes: int = 65536,
    timings: dict[str, float] | None = None,
) -> IngestionReport:
    """Caller supplies checksum-verified immutable bytes and owns commit/rollback.

    Never delete spool data here. The runtime acknowledges a segment only after
    the surrounding transaction commits. Replaying the same identity resumes
    from its offset; identical records at different positions remain distinct.
    """
    timer = PhaseTimer(timings)
    if not 1 <= batch_size <= 10000 or not 1 <= max_line_bytes <= 1024**2:
        raise ValueError("Invalid ingestion batch limits")
    if source.router_id != policy.flow.router_id:
        raise SpoolError("source_router_mismatch")
    if hashlib.sha256(payload).hexdigest() != segment.checksum:
        raise SpoolError("segment_checksum_mismatch")
    repository = BandwidthFlowRepository(db)
    stream = await repository.lock_stream(source.stream_id, source.router_id, policy.digest, time_ns())
    timer.mark("segment_lock_ms")
    progress_rows = await db.scalars(
        select(BandwidthFlowSegment)
        .where(
            BandwidthFlowSegment.stream_id == source.stream_id,
            BandwidthFlowSegment.segment_id == segment.segment_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    progress = progress_rows.one_or_none()
    if progress is None:
        progress = BandwidthFlowSegment(
            stream_id=source.stream_id,
            segment_id=segment.segment_id,
            checksum=segment.checksum,
            size_bytes=len(payload),
            offset_bytes=0,
            accepted_count=0,
            rejected_count=0,
            completed=False,
        )
        db.add(progress)
        await db.flush()
    if progress.checksum != segment.checksum or progress.size_bytes != len(payload):
        raise SpoolError("segment_identity_changed")
    timer.mark("checkpoint_load_ms")
    stream.heartbeat_ns = time_ns()
    stream.status = "running"
    stream.last_error_code = None
    if progress.completed:
        return IngestionReport(0, 0, progress.offset_bytes, True)
    if progress.offset_bytes and payload[progress.offset_bytes - 1 : progress.offset_bytes] != b"\n":
        raise SpoolError("invalid_checkpoint_boundary")
    cursor = BytesIO(payload)
    cursor.seek(progress.offset_bytes)
    accepted: list[tuple[int, ClassifiedFlow]] = []
    rejected: Counter[str] = Counter()
    for _ in range(batch_size):
        offset = cursor.tell()
        # Consume at most a sealed segment, already bounded by the runtime. Long
        # lines are one rejected record, not fragments counted repeatedly.
        line = cursor.readline()
        if not line:
            break
        try:
            accepted.append((offset, _parse(line, policy, max_line_bytes)))
        except FlowRejected as error:
            rejected[error.reason.value] += 1
        except SpoolError as error:
            rejected[str(error)] += 1

    timer.mark("parse_classify_ms")
    identities = await repository.resolve_clients([flow for _, flow in accepted])
    timer.mark("resolve_clients_ms")
    inserts = []
    for (offset, item), client_id in zip(accepted, identities, strict=True):
        flow = item.flow
        inserts.append(
            dict(
                stream_id=source.stream_id,
                segment_id=segment.segment_id,
                record_offset=offset,
                router_id=source.router_id,
                client_id=client_id,
                direction=item.direction.value,
                device_ip=str(item.device_ip),
                remote_ip=str(item.remote_ip),
                source_ip=str(flow.source),
                destination_ip=str(flow.destination),
                post_nat_source=str(flow.post_nat_source) if flow.post_nat_source else None,
                post_nat_destination=str(flow.post_nat_destination) if flow.post_nat_destination else None,
                input_interface=flow.input_interface,
                output_interface=flow.output_interface,
                byte_count=flow.bytes,
                packets=flow.packets,
                started_ns=flow.started_ns,
                ended_ns=flow.ended_ns,
                received_ns=flow.received_ns,
            )
        )
    if inserts:
        await insert_flow_rows(db, inserts)
        timer.mark("insert_flows_ms")
        await increment_daily_usage(
            db, [(item, client_id) for (_, item), client_id in zip(accepted, identities, strict=True)]
        )
        timer.mark("daily_aggregate_ms")
    else:
        timer.mark("insert_flows_ms")
    for reason, count in rejected.items():
        counter_rows = await db.scalars(
            select(BandwidthFlowRejection)
            .where(
                BandwidthFlowRejection.stream_id == source.stream_id,
                BandwidthFlowRejection.reason == reason,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        counter = counter_rows.one_or_none()
        if counter is None:
            counter = BandwidthFlowRejection(stream_id=source.stream_id, reason=reason, record_count=0)
            db.add(counter)
        counter.record_count += count
    progress.offset_bytes = cursor.tell()
    progress.accepted_count += len(accepted)
    progress.rejected_count += sum(rejected.values())
    progress.completed = progress.offset_bytes == len(payload)
    await db.flush()
    timer.mark("checkpoint_rejections_flush_ms")
    return IngestionReport(len(accepted), sum(rejected.values()), progress.offset_bytes, progress.completed)


async def insert_flow_rows(db: AsyncSession, rows: list[dict], *, chunk_size: int = 0) -> int:
    """Insert within the caller's transaction; zero preserves the current bulk path.

    The opt-in chunk size is for controlled tests; never commit partial chunks.
    """
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or not 0 <= chunk_size <= 10000:
        raise ValueError("Invalid flow insert chunk size")
    if not rows:
        return 0
    width = chunk_size or len(rows)
    calls = 0
    for start in range(0, len(rows), width):
        await db.execute(insert(BandwidthFlow), rows[start:start + width])
        calls += 1
    return calls


async def pending_segment(db: AsyncSession, stream_id: str) -> BandwidthFlowSegment | None:
    rows = await db.scalars(
        select(BandwidthFlowSegment)
        # IS FALSE can prevent MySQL from using both pending-index columns.
        # Avoid locking a scan of all completed checkpoints for this stream.
        .with_hint(BandwidthFlowSegment, "FORCE INDEX (ix_bw_segment_pending)", dialect_name="mysql")
        .where(BandwidthFlowSegment.stream_id == stream_id, BandwidthFlowSegment.completed == False)  # noqa: E712
        .order_by(BandwidthFlowSegment.segment_id)
        .with_for_update()
        .limit(1)
    )
    return rows.one_or_none()
