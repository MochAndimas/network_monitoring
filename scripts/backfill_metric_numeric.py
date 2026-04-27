"""Define module logic for `scripts/backfill_metric_numeric.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select, text, update

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.db.session import SessionLocal, engine
from backend.app.models.latest_metric import LatestMetric
from backend.app.models.metric import Metric


NUMERIC_PATTERN = r"^-?[0-9]+(\.[0-9]+)?$"


async def _count_pending_metrics() -> int:
    """Count pending metrics.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    async with SessionLocal() as db:
        query = (
            select(func.count())
            .select_from(Metric)
            .where(
                Metric.metric_value_numeric.is_(None),
                Metric.metric_value.op("REGEXP")(NUMERIC_PATTERN),
            )
        )
        return int(await db.scalar(query) or 0)


async def _next_metric_ids(batch_size: int) -> list[int]:
    """Perform next metric ids.

    Args:
        batch_size: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    async with SessionLocal() as db:
        query = (
            select(Metric.id)
            .where(
                Metric.metric_value_numeric.is_(None),
                Metric.metric_value.op("REGEXP")(NUMERIC_PATTERN),
            )
            .order_by(Metric.id.asc())
            .limit(batch_size)
        )
        return [int(metric_id) for metric_id in (await db.scalars(query)).all()]


async def _backfill_batch(metric_ids: list[int]) -> int:
    """Perform backfill batch.

    Args:
        metric_ids: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    if not metric_ids:
        return 0

    async with SessionLocal() as db:
        await db.execute(
            update(Metric)
            .where(Metric.id.in_(metric_ids))
            .values(metric_value_numeric=text("CAST(metric_value AS DOUBLE)"))
        )
        await db.execute(
            update(LatestMetric)
            .where(LatestMetric.metric_id.in_(metric_ids))
            .values(metric_value_numeric=text("CAST(metric_value AS DOUBLE)"))
        )
        await db.commit()
    return len(metric_ids)


async def main() -> None:
    """Run the module entrypoint.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    parser = argparse.ArgumentParser(description="Backfill numeric metric values in small non-blocking batches.")
    parser.add_argument("--batch-size", type=int, default=500, help="Rows to update per transaction.")
    parser.add_argument("--sleep-seconds", type=float, default=0.05, help="Pause between batches.")
    parser.add_argument("--max-batches", type=int, default=0, help="Optional limit. Zero means run until done.")
    parser.add_argument("--dry-run", action="store_true", help="Only count pending rows.")
    args = parser.parse_args()

    batch_size = max(int(args.batch_size), 1)
    pending = await _count_pending_metrics()
    print(f"Pending numeric metric rows: {pending}")
    if args.dry_run or pending == 0:
        return

    total_updated = 0
    batch_count = 0
    while True:
        if args.max_batches and batch_count >= args.max_batches:
            break
        metric_ids = await _next_metric_ids(batch_size)
        if not metric_ids:
            break
        updated = await _backfill_batch(metric_ids)
        total_updated += updated
        batch_count += 1
        print(f"Batch {batch_count}: updated={updated} total_updated={total_updated}")
        if args.sleep_seconds > 0:
            await asyncio.sleep(args.sleep_seconds)

    remaining = await _count_pending_metrics()
    print(f"Backfill complete for this run. Updated={total_updated}; remaining={remaining}")


if __name__ == "__main__":
    async def _run() -> None:
        try:
            await main()
        finally:
            await engine.dispose()

    asyncio.run(_run())
