"""Exercise real lifecycle/repository boundaries with explicit runtime dependencies."""

from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.app.alerting.engine_parts.dependencies import AlertEvaluationDependencies
from backend.app.alerting.engine_parts.impl import evaluate_alerts
from backend.app.alerting.notifiers.telegram_notifier import TelegramNotifier
from backend.app.core.config import settings
from backend.app.models import Alert, Device, Incident, LatestMetric, Metric
from backend.app.services.run_cycle_service import run_monitoring_cycle
from tests.test_utils import run


def test_injected_clock_controls_alert_and_incident_lifecycle(outbox_sessions):
    timestamp = datetime(2026, 10, 1, 10)

    async def scenario():
        async with outbox_sessions.begin() as db:
            device = Device(name="Clock fixture", ip_address="192.0.2.77", device_type="switch")
            db.add(device)
            await db.flush()
            device_id = device.id
        expected = AsyncMock(
            return_value={
                (device_id, "device_down"): dict(
                    device_id=device_id, alert_type="device_down", severity="critical", message="down"
                )
            }
        )
        writer = AsyncMock()
        sender = AsyncMock(side_effect=AssertionError("inline sender"))
        dependencies = AlertEvaluationDependencies(
            clock=lambda: timestamp,
            expected_alerts=expected,
            legacy_sender=sender,
        )
        async with outbox_sessions() as db:
            created = await evaluate_alerts(db, notification_writer=writer, dependencies=dependencies)
            alert = (await db.scalars(select(Alert))).one()
            incident = (await db.scalars(select(Incident))).one()
            assert created[0]["action"] == "created"
            assert alert.created_at == incident.started_at == timestamp
        later = timestamp + timedelta(hours=1)
        async with outbox_sessions() as db:
            resolved = await evaluate_alerts(
                db,
                notification_writer=writer,
                dependencies=replace(dependencies, clock=lambda: later, expected_alerts=AsyncMock(return_value={})),
            )
            assert resolved[0]["action"] == "resolved"
            assert (await db.scalars(select(Alert))).one().resolved_at == later
            assert (await db.scalars(select(Incident))).one().ended_at == later
        sender.assert_not_awaited()

    run(scenario())


def test_collector_session_and_explicit_numeric_payload_cross_repository_boundary(outbox_sessions):
    collected_sessions = []

    async def scenario():
        async with outbox_sessions.begin() as db:
            device = Device(name="Collector fixture", ip_address="192.0.2.78", device_type="switch")
            db.add(device)
            await db.flush()
            device_id = device.id

        async def collector(db):
            collected_sessions.append(db)
            assert await db.get(Device, device_id) is not None
            return [
                dict(
                    device_id=device_id,
                    metric_name="ping",
                    metric_value="explicit",
                    metric_value_numeric=0.0,
                    status="up",
                    checked_at=datetime(2026, 10, 1, 10),
                )
            ]

        async with outbox_sessions() as db:
            result = await run_monitoring_cycle(db, runners=(collector,), collector_sessions=outbox_sessions)
            assert result["metrics_collected"] == 1
            assert collected_sessions[0] is not db
            assert (await db.scalars(select(Metric))).one().metric_value_numeric == 0.0
            assert (await db.scalars(select(LatestMetric))).one().metric_value_numeric == 0.0

    run(scenario())


@pytest.mark.parametrize("mode", ["accepted", "failed", "unconfigured"])
def test_notifier_injected_transport_has_safe_outcomes(mode, caplog):
    config = replace(settings.telegram, bot_token="fixture-token" if mode != "unconfigured" else "", chat_id="123")
    transport = AsyncMock(side_effect=RuntimeError("fixture-token secret failure") if mode == "failed" else None)
    result = run(TelegramNotifier(config=config, transport=transport).send("fixture message"))
    assert result.accepted is (mode == "accepted")
    assert (
        result.error_category
        == {"accepted": None, "failed": "delivery_failed", "unconfigured": "configuration_missing"}[mode]
    )
    if mode == "unconfigured":
        transport.assert_not_awaited()
    else:
        transport.assert_awaited_once_with(token="fixture-token", chat_id="123", message="fixture message")
    assert "fixture-token" not in caplog.text
