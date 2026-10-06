"""Measure real ASGI group requests against a disposable MySQL fixture.

Refuses a database without the _group_fixture suffix or with existing devices.
Does not start scheduler/collectors, create alerts, or send notifications.
"""

import asyncio
from datetime import timedelta
import json
from statistics import median
from time import perf_counter

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, insert, select, text

from backend.app.core.config import settings
from backend.app.core.time import now
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.models.device import Device
from backend.app.models.latest_metric import LatestMetric
from backend.app.models.metric import Metric


def timing(values):
    ordered = sorted(values)
    return {
        "median_ms": round(median(values), 2),
        "p95_ms": round(ordered[int((len(ordered) - 1) * 0.95)], 2),
        "max_ms": round(max(values), 2),
    }


async def seed():
    if engine.dialect.name != "mysql" or not str(engine.url.database).endswith("_group_fixture"):
        raise RuntimeError("Use a disposable MySQL database ending in _group_fixture")
    if not settings.internal_api_key:
        raise RuntimeError("Use an explicit synthetic INTERNAL_API_KEY")
    timestamp = now()
    async with SessionLocal.begin() as db:
        if await db.scalar(select(func.count()).select_from(Device)) or await db.scalar(
            select(func.count()).select_from(Metric)
        ):
            raise RuntimeError("Fixture device and metric tables must be empty")
        devices = [
            Device(name=f"VoIP fixture {i}", ip_address=f"192.0.2.{i + 1}", device_type="voip", site="fixture")
            for i in range(100)
        ]
        db.add_all(devices)
        await db.flush()
        ids = [device.id for device in devices]
        names = ["ping", "packet_loss", "jitter", "metric_1", "metric_2", "metric_3", "metric_4", "metric_5"]
        payload = []
        for device_id in ids:
            for name in names:
                for sample in range(120):
                    payload.append(
                        dict(
                            device_id=device_id,
                            metric_name=name,
                            metric_value="10",
                            metric_value_numeric=10,
                            status="up",
                            unit="ms",
                            checked_at=timestamp - timedelta(seconds=sample * 30),
                        )
                    )
                    if len(payload) == 2000:
                        await db.execute(insert(Metric), payload)
                        payload = []
        if payload:
            await db.execute(insert(Metric), payload)
        latest_rows = (await db.execute(select(Metric).where(Metric.checked_at == timestamp))).scalars().all()
        db.add_all(
            [
                LatestMetric(
                    metric_id=row.id,
                    device_id=row.device_id,
                    metric_name=row.metric_name,
                    metric_value=row.metric_value,
                    metric_value_numeric=row.metric_value_numeric,
                    status=row.status,
                    unit=row.unit,
                    checked_at=row.checked_at,
                    uptime_streak_started_at=row.checked_at,
                )
                for row in latest_rows
            ]
        )
    return ids, names


async def benchmark():
    ids, names = await seed()
    queries = 0

    def capture(_conn, _cursor, statement, _params, _context, _many):
        nonlocal queries
        if statement.lstrip().upper().startswith("SELECT"):
            queries += 1

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://localhost",
            headers={"x-api-key": settings.internal_api_key},
        ) as client:
            baseline_durations = []
            baseline_bytes = 0
            started = perf_counter()
            for device_id in ids:
                single = perf_counter()
                response = await client.get(
                    "/metrics/history/live",
                    params={
                        "device_id": device_id,
                        "include_selected_device_trend": True,
                        "trend_metric_names": names,
                        "trend_limit": 500,
                        "limit": 500,
                    },
                )
                if response.status_code != 200:
                    raise RuntimeError(f"Baseline HTTP status {response.status_code}")
                baseline_durations.append((perf_counter() - single) * 1000)
                baseline_bytes += len(response.content)
            baseline_wall = (perf_counter() - started) * 1000
            baseline_queries = queries
            queries = 0
            durations: list[float] = []
            sizes: list[int] = []
            query_runs = []
            for cycle in range(3):

                async def refresh(dashboard):
                    started = perf_counter()
                    response = await client.get(
                        "/metrics/history/group", params={"group": "voip", "device_offset": (dashboard % 5) * 20}
                    )
                    elapsed = (perf_counter() - started) * 1000
                    if response.status_code != 200:
                        raise RuntimeError(f"Group HTTP status {response.status_code}")
                    data = response.json()
                    if data["group"]["total_devices"] != 100 or len(data["group"]["devices"]) != 20:
                        raise AssertionError("Incorrect group pagination")
                    if len(response.content) > 1_048_576 or len(data["selected_device_trend"]["items"]) > 2000:
                        raise AssertionError("Payload bound exceeded")
                    return elapsed, len(response.content)

                before = queries
                outcomes = await asyncio.gather(*(refresh(dashboard) for dashboard in range(4)))
                query_runs.append(
                    {"cycle": cycle + 1, "dashboards": 4, "http_requests": 4, "sql_selects": queries - before}
                )
                durations.extend(elapsed for elapsed, _size in outcomes)
                sizes.extend(size for _elapsed, size in outcomes)
            if max(durations) > 2000 or max(run["sql_selects"] for run in query_runs) > 60:
                raise AssertionError("Group latency/query budget failed")
            report = {
                "devices": 100,
                "metrics_per_device": 8,
                "samples_per_pair": 120,
                "raw_metric_rows": 96000,
                "transport": "real FastAPI requests over in-process HTTPX ASGI; no network latency",
                "baseline_one_dashboard": {
                    "http_requests": 100,
                    "sql_selects": baseline_queries,
                    "payload_bytes": baseline_bytes,
                    "sequential_refresh_wall_ms": round(baseline_wall, 2),
                    "request_timings": timing(baseline_durations),
                },
                "group_four_dashboards": {
                    "cycles": query_runs,
                    "timings": timing(durations),
                    "min_payload_bytes": min(sizes),
                    "max_payload_bytes": max(sizes),
                    "device_page_size": 20,
                    "max_trend_items": 2000,
                    "history_per_response": 100,
                },
                "request_count_per_15s_refresh": {"old_four_dashboards": 400, "new_four_dashboards": 4},
                "acceptance": {
                    "passed": True,
                    "max_request_ms": 2000,
                    "max_sql_selects_four_dashboards": 60,
                    "max_payload_bytes": 1_048_576,
                },
            }
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    async with SessionLocal() as db:
        report["mysql_version"] = await db.scalar(text("SELECT VERSION()"))
    return report


async def main():
    try:
        print(json.dumps(await benchmark(), indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
