"""Measure the outbox on an explicitly disposable, migrated MySQL database.

Refuses any database whose name does not end in _outbox_fixture. Never sends to
Telegram. Output contains plans, timings and counts, not notification payloads.
"""

import asyncio
from dataclasses import asdict
import json
from statistics import median
from time import perf_counter
from types import SimpleNamespace

from sqlalchemy import delete, event, func, insert, select, text
from backend.app.core.time import utcnow
from backend.app.db.session import SessionLocal, engine
from backend.app.models.alert import Alert
from backend.app.models.notification_outbox import NotificationOutbox as Job
from backend.app.models.notification_outbox_alert import NotificationOutboxAlert as Reference
from backend.app.models.notification_outbox_stream import NotificationOutboxStream as Stream
from backend.app.models.notification_worker import NotificationWorker
from backend.app.repositories.notification_outbox_repository import NotificationOutboxRepository
from backend.app.services.notification_outbox_health import build_notification_queue_health, active_notification_workers
from backend.app.services.notification_runtime import run_notification_runtime
from backend.app.services.notification_worker import NotificationWorkerPolicy
from backend.app.services.telegram_outbox_writer import TelegramOutboxWriter


def timings(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "median_ms": round(median(ordered), 2),
        "p95_ms": round(ordered[int((len(ordered) - 1) * 0.95)], 2),
        "max_ms": round(max(ordered), 2),
    }


async def benchmark() -> dict:
    if engine.dialect.name != "mysql" or not str(engine.url.database).endswith("_outbox_fixture"):
        raise RuntimeError("Use a disposable MySQL database ending in _outbox_fixture")
    now = utcnow()
    async with SessionLocal() as db:
        if await db.scalar(select(func.count()).select_from(Job)) or await db.scalar(
            select(func.count()).select_from(Alert)
        ):
            raise RuntimeError("Fixture tables must be empty")
        alerts = [
            Alert(alert_type="device_down", severity="critical", status="active", message="synthetic", created_at=now)
            for _ in range(1000)
        ]
        db.add_all(alerts)
        await db.flush()
        events = [
            dict(
                alert_id=a.id,
                alert=a,
                action="active",
                alert_type=a.alert_type,
                severity=a.severity,
                message=a.message,
                device=SimpleNamespace(id=i, name=f"Fixture {i}", site=f"Site {i % 100}"),
            )
            for i, a in enumerate(alerts)
        ]
        started = perf_counter()
        await TelegramOutboxWriter("123")(db, events)
        adapter_ms = (perf_counter() - started) * 1000
        adapter_jobs = await db.scalar(select(func.count()).select_from(Job))
        await db.rollback()
    async with SessionLocal.begin() as db:
        alert = Alert(
            alert_type="device_down", severity="critical", status="active", message="synthetic", created_at=now
        )
        db.add(alert)
        await db.flush()
        alert_id = alert.id
        for offset in range(0, 10000, 1000):
            await db.execute(
                insert(Job),
                [
                    dict(
                        id=i + 1,
                        idempotency_key=f"fixture:{i}",
                        channel="telegram",
                        stream_key=f"fixture:{i % 100}",
                        destination="123",
                        message="synthetic",
                        status="sent" if i < 7000 else ("dead" if 7000 <= i < 7020 else "pending"),
                        available_at=now,
                        created_at=now,
                        updated_at=now,
                        delivered_at=now if i < 7000 else None,
                    )
                    for i in range(offset, offset + 1000)
                ],
            )
        await db.execute(
            insert(Reference), [dict(outbox_id=i + 1, alert_id=alert_id, action="active") for i in range(7000, 10000)]
        )
    # Capture the actual repository candidate SQL, then EXPLAIN it with the same parameters.
    statements = []

    def capture(connection, cursor, statement, parameters, context, many):
        if "NOT (EXISTS" in statement:
            statements.append((statement, parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with SessionLocal() as db:
            await NotificationOutboxRepository(db).claim_next(
                channel="telegram", now=now, lease_seconds=60, max_attempts=5
            )
            await db.rollback()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    plans = []
    async with engine.connect() as connection:
        for statement, parameters in statements:
            result = await connection.exec_driver_sql("EXPLAIN FORMAT=JSON " + statement, parameters)
            plans.append(json.loads(result.scalar_one()))
        result = await connection.execute(
            text(
                "EXPLAIN FORMAT=JSON SELECT status, COUNT(*), MIN(created_at) FROM notification_outbox WHERE channel='telegram' AND status IN ('pending','processing','dead') GROUP BY status"
            )
        )
        plans.append(json.loads(result.scalar_one()))
    baseline: list[float] = []

    async def scrape(target):
        started = perf_counter()
        async with SessionLocal() as db:
            await build_notification_queue_health(db, now=utcnow())
            await active_notification_workers(db, now=utcnow())
        target.append((perf_counter() - started) * 1000)

    for _ in range(20):
        await scrape(baseline)
    concurrent: list[float] = []
    stop = asyncio.Event()
    sends = 0

    async def sender(destination, message):
        nonlocal sends
        await asyncio.sleep(0.02)
        sends += 1
        if sends >= 20:
            stop.set()
        return True

    started = perf_counter()
    worker = asyncio.create_task(
        run_notification_runtime(
            SessionLocal, sender, stop, worker_policy=NotificationWorkerPolicy(concurrency=2, poll_seconds=0.01)
        )
    )
    await asyncio.gather(*(scrape(concurrent) for _ in range(20)))
    report = await asyncio.wait_for(worker, 30)
    report_data = dict(
        workload=dict(jobs=10000, streams=100, sent=7000, dead=20, pending=2980, parallel_scrapes=20),
        adapter=dict(events=1000, sites=100, jobs=adapter_jobs, elapsed_ms=round(adapter_ms, 2)),
        scrape_serial=timings(baseline),
        scrape_parallel_with_worker=timings(concurrent),
        delivery=dict(report=asdict(report), elapsed_ms=round((perf_counter() - started) * 1000, 2)),
        plans=plans,
    )
    async with SessionLocal.begin() as db:
        await db.execute(delete(Reference))
        await db.execute(delete(Job))
        await db.execute(delete(Stream))
        await db.execute(delete(NotificationWorker))
        await db.execute(delete(Alert).where(Alert.id == alert_id))
    return report_data


async def main() -> None:
    try:
        print(json.dumps(await benchmark(), indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
