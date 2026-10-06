"""Regression coverage for bounded history and unchanged sample-based rules."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.alerting.engine_parts.evaluation_context import AlertEvaluationContext
from backend.app.alerting.engine_parts.evaluation_inputs import _load_rolling_metric_history_by_device
from backend.app.alerting.engine_parts.rule_evaluators import evaluate_expected_alerts_for_device
from backend.app.models.device import Device
from backend.app.models.metric import Metric
from backend.app.repositories.metric_repository import MetricRepository
from tests.test_utils import create_all, drop_all, run


def test_history_batches_exact_pairs_and_preserves_time_id_order():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await create_all(engine)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                device = Device(name="fixture", ip_address="192.0.2.1", device_type="switch")
                db.add(device)
                await db.flush()
                now = datetime(2026, 10, 1)
                pairs = [(device.id, f"interface:{i}_tx_mbps") for i in range(67)]
                rows = []
                for device_id, name in pairs:
                    for i in range(9):
                        # Ties, out-of-order arrival, old history and future samples.
                        rows.append(
                            Metric(
                                device_id=device_id,
                                metric_name=name,
                                metric_value=str(i),
                                checked_at=now + timedelta(days=(i % 4) - 2),
                            )
                        )
                db.add_all(rows)
                await db.commit()
                statements = []

                def capture(_conn, _cursor, statement, _parameters, _context, _many):
                    statements.append(statement)

                event.listen(engine.sync_engine, "before_cursor_execute", capture)
                try:
                    history = await MetricRepository(db).list_recent_metrics_by_pairs(
                        pairs=pairs + pairs + [(device.id, "missing")], per_pair_limit=5
                    )
                finally:
                    event.remove(engine.sync_engine, "before_cursor_execute", capture)
                assert len(statements) == 2
                assert "missing" not in history[device.id]
                for _device_id, name in pairs:
                    expected = sorted(
                        [row for row in rows if row.metric_name == name],
                        key=lambda row: (row.checked_at, row.id),
                        reverse=True,
                    )[:5]
                    assert [row.id for row in history[device.id][name]] == [row.id for row in expected]
                assert await MetricRepository(db).list_recent_metrics_by_pairs(pairs=[], per_pair_limit=5) == {}
                assert await MetricRepository(db).list_recent_metrics_by_pairs(pairs=pairs, per_pair_limit=0) == {}
                compatibility = await MetricRepository(db).list_recent_metrics_by_device(
                    device_ids=[device.id, device.id], metric_name=pairs[0][1], per_device_limit=2
                )
                assert compatibility[device.id] == history[device.id][pairs[0][1]][:2]
        finally:
            await drop_all(engine)

    run(scenario())


def test_rolling_loader_keeps_recovery_history_and_scopes_dynamic_pairs():
    repo = AsyncMock(spec=MetricRepository)
    repo.list_recent_metrics_by_pairs.return_value = {1: {"ping": []}}
    latest = {
        (1, "ping"): Metric(),
        (1, "cpu_percent"): Metric(),
        (2, "interface:wan_tx_mbps"): Metric(),
        (3, "interface:other_rx_mbps"): Metric(),
    }
    result = run(_load_rolling_metric_history_by_device(repo, [1, 2], latest_metrics=latest))
    repo.list_recent_metrics_by_pairs.assert_awaited_once_with(
        pairs=[
            (1, "jitter"),
            (1, "packet_loss"),
            (1, "ping"),
            (2, "interface:wan_tx_mbps"),
            (2, "jitter"),
            (2, "packet_loss"),
            (2, "ping"),
        ],
        per_pair_limit=5,
    )
    assert result == {1: {"ping": []}}


@pytest.mark.parametrize(
    "values,triggered",
    [
        ([200], True),
        ([200, 1], True),
        ([200, 1, 1], False),
        ([200, 200, 200], True),
        ([200, 200, 1, 1, 1, 200], False),
        ([200, 200, 200, 1, 1, 1], True),
        ([200, "invalid", "invalid"], False),
    ],
)
@pytest.mark.parametrize("sample_gap_days", [0, 30])
def test_alert_decisions_at_fifth_sample_and_sparse_time_boundary(values, triggered, sample_gap_days):
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await create_all(engine)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                device = Device(name="fixture", ip_address="192.0.2.1", device_type="switch")
                db.add(device)
                await db.flush()
                latest_time = datetime(2026, 10, 1)
                rows = [
                    Metric(
                        device_id=device.id,
                        metric_name="ping",
                        metric_value=str(value),
                        status="up",
                        checked_at=latest_time - timedelta(days=i * sample_gap_days, seconds=i),
                    )
                    for i, value in enumerate(values)
                ]
                db.add_all(rows)
                await db.commit()
                history = await _load_rolling_metric_history_by_device(
                    MetricRepository(db), [device.id], latest_metrics={(device.id, "ping"): rows[0]}
                )
                context = AlertEvaluationContext(
                    device=device,
                    latest_metrics={(device.id, "ping"): rows[0]},
                    thresholds={"ping_latency_warning": 100, "ping_latency_critical": 150},
                    threshold_overrides=[],
                    expected_alerts={},
                    printer_uptime_history_by_device={},
                    internet_service_history_by_device={},
                    metric_history_by_device=history,
                )
                evaluate_expected_alerts_for_device(context)
                assert ((device.id, "high_ping_latency_critical") in context.expected_alerts) is triggered
        finally:
            await drop_all(engine)

    run(scenario())


@pytest.mark.parametrize(
    "statuses,held", [(["up"], True), (["up", "up", "down"], True), (["up", "up", "up", "down"], False)]
)
def test_reachability_recovery_uses_history_even_without_latest_snapshot(statuses, held):
    from backend.app.alerting.engine_parts.evaluation_inputs import _expected_alert_map
    from backend.app.models.alert import Alert

    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await create_all(engine)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                device = Device(name="fixture", ip_address="192.0.2.1", device_type="switch")
                db.add(device)
                await db.flush()
                db.add_all(
                    [
                        Metric(
                            device_id=device.id,
                            metric_name="ping",
                            metric_value="1",
                            status=status,
                            checked_at=datetime(2026, 10, 1) - timedelta(seconds=i),
                        )
                        for i, status in enumerate(statuses)
                    ]
                )
                await db.commit()
                result = await _expected_alert_map(
                    metric_repository=MetricRepository(db),
                    devices=[device],
                    latest_metrics={},
                    thresholds={},
                    threshold_overrides=[],
                    active_maintenance_windows=[],
                    active_alerts=[
                        Alert(device_id=device.id, alert_type="device_down", severity="critical", message="down")
                    ],
                )
                assert ((device.id, "device_down") in result) is held
        finally:
            await drop_all(engine)

    run(scenario())


@pytest.mark.parametrize(
    "metric_name,device_type,values,expected_type",
    [
        ("packet_loss", "switch", [40, 40, 40, 0, 0], "high_packet_loss_critical"),
        ("jitter", "switch", [40, 40, 0, 0, 0, 40], None),
        ("ping", "switch", [60, 10, 10, 10, 10], "ping_latency_anomaly"),
        ("interface:wan:tx_mbps", "mikrotik", [60, 10, 10, 10, 10], "mikrotik_interface_traffic_anomaly"),
        ("dns_resolution_time", "internet_target", [200], None),
        ("http_response_time", "internet_target", [200, 200], "slow_http_response"),
        ("printer_uptime_seconds", "printer", [10, 1000], "printer_reboot_detected"),
    ],
)
def test_other_history_rules_preserve_decisions(metric_name, device_type, values, expected_type):
    from backend.app.alerting.engine_parts.evaluation_inputs import _expected_alert_map

    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await create_all(engine)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                device = Device(name="fixture", ip_address="192.0.2.1", device_type=device_type)
                db.add(device)
                await db.flush()
                rows = [
                    Metric(
                        device_id=device.id,
                        metric_name=metric_name,
                        metric_value=str(value),
                        status="up",
                        checked_at=datetime(2026, 10, 1) - timedelta(days=i),
                    )
                    for i, value in enumerate(values)
                ]
                db.add_all(rows)
                await db.commit()
                result = await _expected_alert_map(
                    metric_repository=MetricRepository(db),
                    devices=[device],
                    latest_metrics={(device.id, metric_name): rows[0]},
                    thresholds={
                        "packet_loss_warning": 10,
                        "packet_loss_critical": 30,
                        "jitter_warning": 10,
                        "jitter_critical": 30,
                        "ping_latency_warning": 100,
                        "ping_latency_critical": 150,
                        "dns_resolution_warning": 100,
                        "http_response_warning": 100,
                        "mikrotik_interface_mbps_warning": 1000,
                    },
                    threshold_overrides=[],
                    active_maintenance_windows=[],
                    active_alerts=[],
                )
                assert {alert_type for _, alert_type in result} == ({expected_type} if expected_type else set())
        finally:
            await drop_all(engine)

    run(scenario())


@pytest.mark.parametrize("offset_seconds,included", [(-1, False), (0, False), (1, True)])
def test_dynamic_staleness_boundary_keeps_existing_policy(monkeypatch, offset_seconds, included):
    from backend.app.alerting.engine_parts import impl

    now = datetime(2026, 10, 1)
    stale_age = impl._alert_metric_stale_after_seconds()
    dynamic_key = (1, "interface:wan:tx_mbps")
    filtered = impl._drop_stale_dynamic_alert_metrics(
        {
            dynamic_key: Metric(checked_at=now - timedelta(seconds=stale_age) + timedelta(seconds=offset_seconds)),
            (1, "ping"): Metric(checked_at=now - timedelta(days=30)),
        },
        current_time=now,
    )
    assert (dynamic_key in filtered) is included
    assert (1, "ping") in filtered
    repository = AsyncMock(spec=MetricRepository)
    repository.list_recent_metrics_by_pairs.return_value = {}
    run(impl._load_rolling_metric_history_by_device(repository, [1], latest_metrics=filtered))
    queried_pairs = repository.list_recent_metrics_by_pairs.call_args.kwargs["pairs"]
    assert (dynamic_key in queried_pairs) is included
    assert (1, "ping") in queried_pairs
