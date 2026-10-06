"""Compare rolling alert evaluation on a disposable migrated MySQL fixture.

Requires an empty database ending in _rolling_fixture. Does not collect metrics,
write alerts, or send notifications. Samples and devices are synthetic. Writes
JSON to stdout; pass an explicit output path through shell redirection.
"""

import asyncio
from typing import Any
from datetime import datetime, timedelta
import json
from statistics import median
from time import perf_counter

from sqlalchemy import desc, event, func, insert, select, text

from backend.app.alerting.engine_parts.impl import _expected_alert_map
from backend.app.db.session import SessionLocal, engine
from backend.app.models.device import Device
from backend.app.models.metric import Metric
from backend.app.repositories.metric_repository import MetricRepository
from backend.app.repositories.metrics.alert_history import recent_metric_pairs_query


class RankingBaseline(MetricRepository):
    """Reproduce the original name-by-name, cross-device window ranking."""

    async def list_recent_metrics_by_pairs(self, *, pairs, per_pair_limit=5):
        payload: dict[int, dict[str, list[Metric]]] = {}
        device_ids = sorted({device_id for device_id, _ in pairs})
        for name in sorted({name for _, name in pairs}):
            ranked = (
                select(
                    Metric.id.label("metric_id"),
                    func.row_number()
                    .over(partition_by=Metric.device_id, order_by=(desc(Metric.checked_at), desc(Metric.id)))
                    .label("rank"),
                )
                .where(Metric.device_id.in_(device_ids), Metric.metric_name == name)
                .subquery()
            )
            query = (
                select(Metric)
                .join(ranked, Metric.id == ranked.c.metric_id)
                .where(ranked.c.rank <= per_pair_limit)
                .order_by(Metric.device_id, desc(Metric.checked_at), desc(Metric.id))
            )
            for metric in (await self.db.scalars(query)).all():
                payload.setdefault(metric.device_id, {}).setdefault(name, []).append(metric)
        return payload


async def examined_rows(db):
    value = await db.scalar(
        text("""
        SELECT COALESCE(SUM(SUM_ROWS_EXAMINED), 0)
        FROM performance_schema.events_statements_summary_by_thread_by_event_name
        WHERE THREAD_ID = (SELECT THREAD_ID FROM performance_schema.threads
                           WHERE PROCESSLIST_ID = CONNECTION_ID())
          AND EVENT_NAME = 'statement/sql/select'
    """)
    )
    return int(value or 0)


async def measure(repository_type, devices, latest):
    runs = []
    expected = None
    thresholds = {
        "ping_latency_warning": 100,
        "ping_latency_critical": 150,
        "packet_loss_warning": 10,
        "packet_loss_critical": 30,
        "jitter_warning": 10,
        "jitter_critical": 30,
        "mikrotik_interface_mbps_warning": 1000,
        "dns_resolution_warning": 100,
        "http_response_warning": 100,
    }
    for _ in range(3):
        async with SessionLocal() as db:
            before = await examined_rows(db)
            query_count = 0

            def capture(_conn, _cursor, statement, _params, _context, _many):
                nonlocal query_count
                if statement.lstrip().upper().startswith("SELECT"):
                    query_count += 1

            event.listen(engine.sync_engine, "before_cursor_execute", capture)
            started = perf_counter()
            try:
                result = await _expected_alert_map(
                    metric_repository=repository_type(db),
                    devices=devices,
                    latest_metrics=latest,
                    thresholds=thresholds,
                    threshold_overrides=[],
                    active_maintenance_windows=[],
                    active_alerts=[],
                )
            finally:
                elapsed = (perf_counter() - started) * 1000
                event.remove(engine.sync_engine, "before_cursor_execute", capture)
            after = await examined_rows(db)
            result = {
                key: {field: value for field, value in payload.items() if field != "created_at"}
                for key, payload in result.items()
            }
            if expected is not None and result != expected:
                raise AssertionError("Unstable alert decisions")
            expected = result
            runs.append({"duration_ms": round(elapsed, 2), "query_count": query_count, "rows_examined": after - before})
    return {"runs": runs, "median_ms": round(median(r["duration_ms"] for r in runs), 2)}, expected


async def benchmark():
    if engine.dialect.name != "mysql" or not str(engine.url.database).endswith("_rolling_fixture"):
        raise RuntimeError("Use a disposable migrated MySQL database ending in _rolling_fixture")
    async with SessionLocal() as db:
        if await db.scalar(select(func.count()).select_from(Device)) or await db.scalar(
            select(func.count()).select_from(Metric)
        ):
            raise RuntimeError("Fixture device/metric tables must be empty")
        enabled = await db.scalar(
            text("SELECT ENABLED FROM performance_schema.setup_instruments WHERE NAME = 'statement/sql/select'")
        )
        if enabled != "YES":
            raise RuntimeError("Enable performance_schema statement/sql/select for rows examined")
    now = datetime(2026, 10, 1, 12)
    async with SessionLocal.begin() as db:
        devices = [
            Device(
                name=f"Fixture {i}",
                ip_address=f"192.0.2.{i + 1}",
                device_type="internet_target" if i < 10 else "mikrotik",
            )
            for i in range(100)
        ]
        db.add_all(devices)
        await db.flush()
    pairs = [(device.id, name) for device in devices for name in ("ping", "packet_loss", "jitter")]
    pairs += [
        (device.id, f"interface:device{device.id}_port{port}:tx_mbps") for device in devices[10:] for port in range(2)
    ]
    pairs += [(device.id, name) for device in devices[:10] for name in ("dns_resolution_time", "http_response_time")]
    report: dict[str, Any] = {
        "mysql_version": "",
        "devices": len(devices),
        "pairs": len(pairs),
        "pair_batch_size": 64,
        "sample_window": 5,
        "workloads": [],
    }
    previous_samples = 0
    for samples in (10, 1000):
        async with SessionLocal.begin() as db:
            payload = []
            for device_id, name in pairs:
                for i in range(previous_samples, samples):
                    # Five newest include tied times; old samples cross day boundaries.
                    payload.append(
                        dict(
                            device_id=device_id,
                            metric_name=name,
                            metric_value="200" if i == 0 else "10",
                            metric_value_numeric=200 if i == 0 else 10,
                            status="up",
                            unit="ms",
                            checked_at=now - timedelta(minutes=i // 2),
                        )
                    )
                    if len(payload) == 2000:
                        await db.execute(insert(Metric), payload)
                        payload = []
            if payload:
                await db.execute(insert(Metric), payload)
        previous_samples = samples
        async with SessionLocal() as db:
            histories = await MetricRepository(db).list_recent_metrics_by_pairs(pairs=pairs, per_pair_limit=5)
            latest = {
                (device_id, name): rows[0] for device_id, by_name in histories.items() for name, rows in by_name.items()
            }
            report["mysql_version"] = await db.scalar(text("SELECT VERSION()"))
        baseline, baseline_alerts = await measure(RankingBaseline, devices, latest)
        bounded, bounded_alerts = await measure(MetricRepository, devices, latest)
        if baseline_alerts != bounded_alerts:
            raise AssertionError("Alert decisions changed")
        report["workloads"].append(
            {
                "samples_per_pair": samples,
                "metric_rows": samples * len(pairs),
                "baseline": baseline,
                "bounded": bounded,
                "decisions_equal": True,
                "alert_count": len(bounded_alerts or {}),
            }
        )
    async with SessionLocal() as db:
        query = recent_metric_pairs_query(pairs[:64], per_pair_limit=5)
        compiled = query.compile(dialect=engine.dialect, compile_kwargs={"literal_binds": True})
        report["explain_analyze_64_pairs"] = list((await db.scalars(text("EXPLAIN ANALYZE " + str(compiled)))).all())
    return report


async def main():
    try:
        report = await benchmark()
        validate_report(report)
        print(json.dumps(report, indent=2))
    finally:
        await engine.dispose()


def validate_report(report: dict[str, Any]) -> None:
    """Fail the fixed 100-device fixture if cost or decision budgets regress."""
    budgets = {"max_queries": 10, "max_rows_examined": 10000, "max_median_ms": 1000}
    for workload in report["workloads"]:
        bounded = workload["bounded"]
        if not workload["decisions_equal"] or bounded["median_ms"] > budgets["max_median_ms"]:
            raise AssertionError("Alert decisions or evaluation latency budget failed")
        if any(
            run["query_count"] > budgets["max_queries"] or not 0 < run["rows_examined"] <= budgets["max_rows_examined"]
            for run in bounded["runs"]
        ):
            raise AssertionError("Query/rows-examined budget failed")
    examined = [workload["bounded"]["runs"][0]["rows_examined"] for workload in report["workloads"]]
    if max(examined) > min(examined) * 1.05:
        raise AssertionError("Bounded history cost grew with historical volume")
    report["acceptance"] = {"budgets": budgets, "passed": True, "max_rows_growth_ratio": 1.05}


if __name__ == "__main__":
    asyncio.run(main())
