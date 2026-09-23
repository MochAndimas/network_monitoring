"""Run the real evaluator with a transactional writer and fixture-only delivery."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from backend.app.alerting.engine import evaluate_alerts
from backend.app.alerting import engine as engine_facade
from backend.app.alerting.engine_parts import impl
from backend.app.alerting.engine_parts.notification_formatting import _build_telegram_message
from backend.app.core.time import utcnow
from backend.app.models import Alert, Device, Incident, NotificationOutbox, Threshold
from backend.app.repositories.metric_repository import MetricRepository
from backend.app.repositories.notification_outbox_repository import NotificationDraft
from backend.app.services.alert_notification_outbox_service import (
    AlertNotificationReference,
    deliver_alert_notification,
    enqueue_alert_notification,
    pending_active_notification_ids,
)
from tests.test_utils import run


async def seed(db):
    now = utcnow()
    device = Device(name="Fixture", ip_address="10.176.0.1", site="fixture", device_type="switch")
    db.add(device)
    await db.flush()
    alert = Alert(
        device_id=device.id,
        alert_type="device_down",
        severity="critical",
        message="Fixture down",
        status="active",
        created_at=now - timedelta(hours=2),
    )
    db.add_all([alert, Incident(device_id=device.id, status="active", summary="Fixture", started_at=alert.created_at)])
    await db.flush()
    job_id = await enqueue_alert_notification(
        db,
        NotificationDraft("initial", "fixture", "telegram", "ACTIVE"),
        (AlertNotificationReference(alert.id, "active"),),
        now=now,
    )
    return alert.id, device.id, job_id


async def write_fixture_events(db, events):
    # The production grouping/destination adapter remains a separate integration
    # step. This fixture writes real outbox jobs through the supported contract.
    for event in events:
        assert event["action"] == "resolved"
        await enqueue_alert_notification(
            db,
            NotificationDraft(f"resolved:{event['alert_id']}", "fixture", "telegram", _build_telegram_message([event])),
            (AlertNotificationReference(event["alert_id"], "resolved"),),
            now=utcnow(),
        )


@pytest.mark.parametrize("commit", [True, False])
def test_writer_failure_never_commits_domain_or_threshold_defaults(outbox_sessions, monkeypatch, commit):
    # Stub only the rule decision, leaving repository writes, incident transitions,
    # threshold initialization, event selection, and transaction logic real.
    monkeypatch.setattr(impl, "_expected_alert_map", AsyncMock(return_value={}))
    sender = AsyncMock(side_effect=AssertionError("Direct transport must not run"))
    monkeypatch.setattr(engine_facade, "send_telegram_alert", sender)

    async def failed_writer(db, events):
        assert len(events) == 1
        await write_fixture_events(db, events)
        raise RuntimeError("enqueue failed")

    async def scenario():
        async with outbox_sessions.begin() as db:
            alert_id, _, _ = await seed(db)
        with pytest.raises(RuntimeError, match="enqueue failed"):
            async with outbox_sessions.begin() as db:
                await evaluate_alerts(db, commit=commit, notification_writer=failed_writer)
        async with outbox_sessions() as db:
            alert = await db.get(Alert, alert_id)
            assert alert is not None and alert.status == "active" and alert.telegram_notified_at is None
            assert await db.scalar(select(func.count()).select_from(NotificationOutbox)) == 1
            assert await db.scalar(select(func.count()).select_from(Threshold)) == 0
            assert (await db.scalars(select(Incident.status))).all() == ["active"]
        sender.assert_not_awaited()

    run(scenario())


@pytest.mark.parametrize("commit", [True, False])
def test_pending_active_resolution_is_queued_and_delivered_in_order(outbox_sessions, monkeypatch, commit):
    monkeypatch.setattr(impl, "_expected_alert_map", AsyncMock(return_value={}))

    async def scenario():
        async with outbox_sessions.begin() as db:
            alert_id, _, _ = await seed(db)
        async with outbox_sessions.begin() as db:
            await evaluate_alerts(db, commit=commit, notification_writer=write_fixture_events)
        async with outbox_sessions() as db:
            alert = await db.get(Alert, alert_id)
            assert alert is not None and alert.status == "resolved" and alert.telegram_notified_at is None
            assert (await db.scalars(select(NotificationOutbox.status).order_by(NotificationOutbox.id))).all() == [
                "pending",
                "pending",
            ]
        sender = AsyncMock(return_value=True)
        assert await deliver_alert_notification(outbox_sessions, sender) == "sent"
        assert sender.call_args.args[0] == "ACTIVE"
        assert await deliver_alert_notification(outbox_sessions, sender) == "sent"
        assert "ALERT RESOLVED" in sender.call_args.args[0]
        assert await deliver_alert_notification(outbox_sessions, sender) == "idle"

    run(scenario())


def test_outer_rollback_after_successful_enqueue_keeps_alert_active(outbox_sessions, monkeypatch):
    monkeypatch.setattr(impl, "_expected_alert_map", AsyncMock(return_value={}))

    async def scenario():
        async with outbox_sessions.begin() as db:
            alert_id, _, _ = await seed(db)
        with pytest.raises(RuntimeError, match="outer rollback"):
            async with outbox_sessions.begin() as db:
                await evaluate_alerts(db, commit=False, notification_writer=write_fixture_events)
                raise RuntimeError("outer rollback")
        async with outbox_sessions() as db:
            alert = await db.get(Alert, alert_id)
            assert alert is not None and alert.status == "active"
            assert await db.scalar(select(func.count()).select_from(NotificationOutbox)) == 1

    run(scenario())


@pytest.mark.parametrize("status", ["pending", "processing", "dead"])
def test_evaluation_does_not_repeat_active_owned_by_outbox(outbox_sessions, status):
    async def scenario():
        async with outbox_sessions.begin() as db:
            alert_id, device_id, job_id = await seed(db)
            job = await db.get(NotificationOutbox, job_id)
            assert job is not None
            job.status = status
            await MetricRepository(db).create_metrics(
                [dict(device_id=device_id, metric_name="ping", metric_value="0", status="down", checked_at=utcnow())],
                commit=False,
            )
        writer = AsyncMock()
        async with outbox_sessions.begin() as db:
            await evaluate_alerts(db, commit=False, notification_writer=writer)
            assert await pending_active_notification_ids(db, {alert_id}) == {alert_id}
        writer.assert_awaited_once()
        assert writer.call_args.args[1] == []

    run(scenario())


def test_sent_active_releases_pending_ownership(outbox_sessions):
    async def scenario():
        async with outbox_sessions.begin() as db:
            alert_id, _, _ = await seed(db)
            assert await pending_active_notification_ids(db, {alert_id}) == {alert_id}
        assert await deliver_alert_notification(outbox_sessions, AsyncMock(return_value=True)) == "sent"
        async with outbox_sessions() as db:
            assert await pending_active_notification_ids(db, {alert_id}) == set()
            assert await pending_active_notification_ids(db, set()) == set()

    run(scenario())


@pytest.mark.parametrize("commit", [True, False])
def test_failed_writer_rolls_back_new_alert_and_incident(outbox_sessions, monkeypatch, commit):
    async def scenario():
        async with outbox_sessions.begin() as db:
            device = Device(name="New fixture", ip_address="10.176.0.2", site="fixture", device_type="switch")
            db.add(device)
            await db.flush()
            device_id = device.id
        monkeypatch.setattr(
            impl,
            "_expected_alert_map",
            AsyncMock(
                return_value={
                    (device_id, "device_down"): dict(
                        device_id=device_id, alert_type="device_down", severity="critical", message="Fixture"
                    )
                }
            ),
        )

        async def fail_after_domain_write(db, events):
            assert await db.scalar(select(func.count()).select_from(Alert)) == 1
            assert await db.scalar(select(func.count()).select_from(Incident)) == 1
            raise RuntimeError("writer failure")

        with pytest.raises(RuntimeError, match="writer failure"):
            async with outbox_sessions.begin() as db:
                await evaluate_alerts(db, commit=commit, notification_writer=fail_after_domain_write)
        async with outbox_sessions() as db:
            for model in (Alert, Incident, Threshold, NotificationOutbox):
                assert await db.scalar(select(func.count()).select_from(model)) == 0

    run(scenario())
