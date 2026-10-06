"""Exercise bounded retention on an empty, disposable MySQL retention fixture.

Refuses databases without the _retention_fixture suffix. Does not start scheduler,
collectors or notifications. Run with APP_ENV_FILE='' and a fixture DATABASE_URL.
"""

import asyncio
from datetime import timedelta
import json
import re
from statistics import median
from time import perf_counter

from sqlalchemy import event, func, insert, select, text

from backend.app.core.config import settings
from backend.app.core.time import utcnow
from backend.app.db.session import SessionLocal, engine
from backend.app.models.device import Device
from backend.app.models.metric import Metric
from backend.app.models.latest_metric import LatestMetric
from backend.app.models.metric_cold_archive import MetricColdArchive
from backend.app.models.metric_daily_rollup import MetricDailyRollup
from backend.app.services.retention_service import cleanup_monitoring_data


async def seed() -> None:
    if engine.dialect.name != "mysql" or not str(engine.url.database).endswith("_retention_fixture"):
        raise RuntimeError("Use a disposable MySQL database ending in _retention_fixture")
    async with SessionLocal() as db:
        if await db.scalar(select(func.count()).select_from(Device)) or await db.scalar(
            select(func.count()).select_from(Metric)
        ):
            raise RuntimeError("Fixture must have empty device and metric tables")
        devices = [
            Device(name=f"Retention fixture {i}", ip_address=f"192.0.2.{i + 1}", device_type="voip", site="fixture")
            for i in range(100)
        ]
        db.add_all(devices)
        await db.commit()
        ids = [device.id for device in devices]
    timestamp = utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=10)
    for device_id in ids:
        async with SessionLocal.begin() as db:
            await db.execute(
                insert(Metric),
                [
                    dict(
                        device_id=device_id,
                        metric_name="ping",
                        metric_value=str(i),
                        metric_value_numeric=float(i),
                        status="up",
                        unit="ms",
                        checked_at=timestamp + timedelta(seconds=i),
                    )
                    for i in range(1000)
                ],
            )
            row = await db.scalar(
                select(Metric).where(Metric.device_id == device_id).order_by(Metric.id.desc()).limit(1)
            )
            if row is None:
                raise RuntimeError("Fixture seed produced no latest metric")
            db.add(
                LatestMetric(
                    metric_id=row.id,
                    device_id=device_id,
                    metric_name="ping",
                    metric_value=row.metric_value,
                    metric_value_numeric=row.metric_value_numeric,
                    status="up",
                    unit="ms",
                    checked_at=row.checked_at,
                )
            )


async def benchmark() -> None:
    await seed()
    settings.retention_source_batch_size = 250
    settings.retention_delete_batch_size = 500
    settings.retention_max_batches_per_phase = 50
    durations: list[float] = []
    max_source_ids = 0
    max_delete_ids = 0
    statements = 0

    def begin(connection):
        connection.info["retention_fixture_started"] = perf_counter()

    def commit(connection):
        started = connection.info.pop("retention_fixture_started", None)
        if started is not None:
            durations.append((perf_counter() - started) * 1000)

    def query(_connection, _cursor, statement, parameters, _context, _many):
        nonlocal statements, max_source_ids, max_delete_ids
        statements += 1
        match = re.search(r"metrics.id IN \(([^)]*)\)", statement)
        if match:
            count = match.group(1).count("%s")
            if statement.lstrip().startswith("DELETE FROM metrics"):
                max_delete_ids = max(max_delete_ids, count)
            else:
                max_source_ids = max(max_source_ids, count)

    event.listen(engine.sync_engine, "begin", begin)
    event.listen(engine.sync_engine, "commit", commit)
    event.listen(engine.sync_engine, "before_cursor_execute", query)
    runs = []
    try:
        for index in range(12):
            started = perf_counter()
            async with SessionLocal() as db:
                result = await cleanup_monitoring_data(db)
            runs.append(dict(run=index + 1, duration_ms=round((perf_counter() - started) * 1000, 2), **result))
            if not result["rolled_up_days"] and not result["archived_metric_groups"] and not result["deleted_metrics"]:
                break
    finally:
        event.remove(engine.sync_engine, "begin", begin)
        event.remove(engine.sync_engine, "commit", commit)
        event.remove(engine.sync_engine, "before_cursor_execute", query)
    async with SessionLocal() as db:
        remaining = int(await db.scalar(select(func.count()).select_from(Metric)) or 0)
        archived = int(await db.scalar(select(func.sum(MetricColdArchive.sample_count))) or 0)
        rolled = int(await db.scalar(select(func.sum(MetricDailyRollup.total_samples))) or 0)
        avg = await db.scalar(select(func.avg(MetricColdArchive.avg_numeric_value)))
        version = await db.scalar(text("SELECT VERSION()"))
    ordered = sorted(durations)
    passed = (
        remaining == 100
        and archived == rolled == 100000
        and avg == 499.5
        and 0 < max_source_ids <= 250
        and 0 < max_delete_ids <= 500
        and max(durations) < 2000
    )
    print(
        json.dumps(
            dict(
                mysql_version=version,
                devices=100,
                raw_metric_rows=100000,
                source_batch_size=250,
                delete_batch_size=500,
                max_batches_per_phase=50,
                runs=runs,
                sql_statements=statements,
                transactions=len(durations),
                transaction_median_ms=round(median(durations), 2),
                transaction_p95_ms=round(ordered[int((len(ordered) - 1) * 0.95)], 2),
                transaction_max_ms=round(max(durations), 2),
                observed_max_source_ids=max_source_ids,
                observed_max_delete_ids=max_delete_ids,
                remaining_latest_metrics=remaining,
                archived_samples=archived,
                rolled_up_samples=rolled,
                acceptance=dict(passed=passed, max_transaction_ms=2000),
            ),
            indent=2,
        )
    )
    await engine.dispose()
    if not passed:
        raise RuntimeError("Retention benchmark acceptance failed")


if __name__ == "__main__":
    asyncio.run(benchmark())
