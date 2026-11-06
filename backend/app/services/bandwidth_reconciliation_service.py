"""Attribute delayed identities and move daily bytes in the same transaction."""

from collections import defaultdict
from dataclasses import dataclass
from time import time_ns
from typing import cast

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..bandwidth.daily import allocate_days
from ..models.bandwidth import BandwidthIPHistory as History
from ..models.bandwidth_daily import BandwidthDailyUsage as Daily
from ..models.bandwidth_ingestion import BandwidthFlow as Flow
from ..repositories.bandwidth_daily_repository import increment_daily_buckets
from ..repositories.bandwidth_inventory_repository import BandwidthInventoryRepository


@dataclass
class ReconciliationCursor:
    """Bounded circular scan; callers publish a copy only after transaction commit."""

    after_id: int = 0
    upper_id: int | None = None


async def reconcile_identities(
    db: AsyncSession, router_id: int, *, batch_size: int = 500,
    cursor: ReconciliationCursor | None = None,
) -> int:
    """Caller owns commit; serialize with ingestion/inventory using the router lock.

    Resolve only NULL flows fully covered by exactly one historical interval.
    Repeating a committed batch is a no-op. Never infer earlier ownership from
    the current IP assignment or combine observations across gaps.
    """
    if not 1 <= batch_size <= 1000:
        raise ValueError("Invalid reconciliation batch size")
    scan = cursor if cursor is not None else ReconciliationCursor()
    if scan.upper_id is None:
        # Global primary-key high water mark, frozen for this pass. New traffic
        # cannot prevent wraparound and rechecking older unresolved identities.
        scan.upper_id = await db.scalar(select(Flow.id).order_by(Flow.id.desc()).limit(1)) or 0
    window_end = min(scan.after_id + 5000, scan.upper_id)
    # Primary-key range bounds examined flow rows, not only matching results.
    # Never run a correlated history query over the entire unresolved backlog.
    candidate_ids = list(await db.scalars(
        select(Flow.id)
        .with_hint(Flow, "FORCE INDEX (PRIMARY)", dialect_name="mysql")
        .where(Flow.id > scan.after_id, Flow.id <= window_end,
               Flow.router_id == router_id, Flow.client_id.is_(None))
        .order_by(Flow.id).limit(batch_size)
    ))
    scan.after_id = candidate_ids[-1] if len(candidate_ids) == batch_size else window_end
    if scan.after_id >= scan.upper_id:
        scan.after_id, scan.upper_id = 0, None
    if not candidate_ids:
        return 0
    await BandwidthInventoryRepository(db).lock_router(router_id)
    flows = list(await db.scalars(
        select(Flow)
        .with_hint(Flow, "FORCE INDEX (PRIMARY)", dialect_name="mysql")
        .where(Flow.id.in_(candidate_ids), Flow.router_id == router_id, Flow.client_id.is_(None))
        .order_by(Flow.id).with_for_update().execution_options(populate_existing=True)
    ))
    if not flows:
        return 0
    # Locking reads see current committed history even under REPEATABLE READ.
    # Recheck after acquiring the router mutex: discovery may now be stale.
    histories = list(await db.scalars(
        select(History).where(
            History.router_id == router_id,
            History.ip_address.in_({flow.device_ip for flow in flows}),
            History.first_observed_ns <= max(flow.ended_ns for flow in flows),
            History.last_observed_ns >= min(flow.started_ns for flow in flows),
        ).limit(10001).with_for_update().execution_options(populate_existing=True)
    ))
    if len(histories) > 10000:
        return 0  # Fail closed for pathological history, never guess an owner.
    by_ip = defaultdict(list)
    for history in histories:
        by_ip[history.ip_address].append(history)
    rows = []
    for flow in flows:
        owners = [history.client_id for history in by_ip[flow.device_ip]
                  if history.first_observed_ns <= flow.started_ns
                  and history.last_observed_ns >= flow.ended_ns]
        if len(owners) == 1:
            rows.append((flow, owners[0]))
    sources: dict[tuple, list[int]] = defaultdict(lambda: [0, 0, 0])
    destinations: dict[tuple, list[int]] = defaultdict(lambda: [0, 0, 0])
    for flow, client_id in rows:
        for day, amount, estimated in allocate_days(flow.started_ns, flow.ended_ns, flow.byte_count):
            if not amount:
                continue
            source = sources[(router_id, day, f"ip:{flow.device_ip}")]
            destination = destinations[(router_id, day, f"c:{client_id}", client_id, None)]
            column = 0 if flow.direction == "upload" else 1
            for totals in (source, destination):
                totals[column] += amount
                totals[2] += amount if estimated else 0
        flow.client_id = client_id
    now = time_ns()
    # Guard subtraction instead of negative upserts: MySQL checks INSERT values
    # before duplicate-key UPDATE. A missing/inconsistent source fails atomically.
    for (router, day, subject), (upload, download, estimated_count) in sorted(sources.items()):
        predicate = (Daily.router_id == router, Daily.day == day, Daily.subject == subject)
        result = await db.execute(
            update(Daily)
            .where(
                *predicate,
                Daily.upload_bytes >= upload,
                Daily.download_bytes >= download,
                Daily.estimated_bytes >= estimated_count,
            )
            .values(
                upload_bytes=Daily.upload_bytes - upload,
                download_bytes=Daily.download_bytes - download,
                estimated_bytes=Daily.estimated_bytes - estimated_count,
                updated_ns=now,
            )
        )
        if cast(CursorResult, result).rowcount != 1:
            raise ValueError("reconciliation_daily_source_mismatch")
        await db.execute(
            delete(Daily).where(
                *predicate, Daily.upload_bytes == 0, Daily.download_bytes == 0, Daily.estimated_bytes == 0
            )
        )
    await increment_daily_buckets(db, destinations, now)
    await db.flush()
    return len(rows)
