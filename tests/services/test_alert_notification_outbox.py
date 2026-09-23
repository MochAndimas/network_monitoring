"""Queue/domain state and delivery acknowledgement must share transactions."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, func, select

from backend.app.core.time import utcnow
from backend.app.models import (
    Alert,
    Device,
    Incident,
    IncidentTimelineEvent,
    NotificationOutbox,
    NotificationOutboxAlert,
)
from backend.app.services.alert_notification_outbox_service import (
    AlertNotificationReference as Ref,
    deliver_alert_notification,
    enqueue_alert_notification,
)
from backend.app.repositories.notification_outbox_repository import NotificationDraft
from backend.app.repositories.incident_repository import IncidentRepository
from tests.test_utils import run


async def seed(db, now):
    device = Device(name="Outbox fixture", ip_address="10.177.0.1", device_type="switch", site="fixture")
    db.add(device)
    await db.flush()
    alert = Alert(
        device_id=device.id,
        alert_type="device_down",
        severity="critical",
        message="fixture",
        status="active",
        created_at=now,
    )
    incident = Incident(device_id=device.id, status="active", summary="fixture", started_at=now)
    db.add_all([alert, incident])
    await db.flush()
    return alert


def test_enqueue_commits_with_alert_without_claiming_delivery(outbox_sessions):
    async def scenario():
        now = utcnow()
        with pytest.raises(RuntimeError, match="rollback"):
            async with outbox_sessions.begin() as db:
                alert = await seed(db, now)
                await enqueue_alert_notification(
                    db,
                    NotificationDraft("rollback", "site", "telegram", "fixture"),
                    (Ref(alert.id, "active"),),
                    now=now,
                )
                raise RuntimeError("rollback")
        async with outbox_sessions.begin() as db:
            for model in (Alert, NotificationOutbox, NotificationOutboxAlert):
                assert await db.scalar(select(func.count()).select_from(model)) == 0
            alert = await seed(db, now)
            payload = NotificationDraft("active", "site", "telegram", "fixture")
            first = await enqueue_alert_notification(db, payload, (Ref(alert.id, "active"),), now=now)
            assert await enqueue_alert_notification(db, payload, (Ref(alert.id, "active"),), now=now) == first
            assert alert.telegram_notified_at is None
            assert await db.scalar(select(func.count()).select_from(IncidentTimelineEvent)) == 0
            with pytest.raises(ValueError, match="different alert references"):
                await enqueue_alert_notification(db, payload, (Ref(alert.id, "resolved"),), now=now)

    run(scenario())


def test_failed_delivery_does_not_mark_domain_and_success_marks_once(outbox_sessions):
    async def scenario():
        now = utcnow()
        async with outbox_sessions.begin() as db:
            alert = await seed(db, now)
            alert_id = alert.id
            await enqueue_alert_notification(
                db, NotificationDraft("active", "site", "telegram", "fixture"), (Ref(alert_id, "active"),), now=now
            )
        assert (
            await deliver_alert_notification(outbox_sessions, AsyncMock(return_value=False), clock=lambda: now)
            == "retry"
        )
        async with outbox_sessions() as db:
            row = await db.get(Alert, alert_id)
            assert row is not None and row.telegram_notified_at is None
            assert await db.scalar(select(func.count()).select_from(IncidentTimelineEvent)) == 0
        delivered = now + timedelta(seconds=5)
        assert (
            await deliver_alert_notification(outbox_sessions, AsyncMock(return_value=True), clock=lambda: delivered)
            == "sent"
        )
        assert (
            await deliver_alert_notification(outbox_sessions, AsyncMock(return_value=True), clock=lambda: delivered)
            == "idle"
        )
        async with outbox_sessions() as db:
            row = await db.get(Alert, alert_id)
            assert row is not None and row.telegram_notified_at == delivered
            assert await db.scalar(select(func.count()).select_from(IncidentTimelineEvent)) == 1

    run(scenario())


def test_domain_ack_failure_rolls_back_job_and_domain_together(outbox_sessions, monkeypatch):
    async def scenario():
        now = utcnow()
        async with outbox_sessions.begin() as db:
            alert = await seed(db, now)
            alert_id = alert.id
            job_id = await enqueue_alert_notification(
                db, NotificationDraft("active", "site", "telegram", "fixture"), (Ref(alert_id, "active"),), now=now
            )
        monkeypatch.setattr(
            IncidentRepository,
            "add_notification_timeline_event_for_alert",
            AsyncMock(side_effect=RuntimeError("timeline failed")),
        )
        with pytest.raises(RuntimeError, match="timeline failed"):
            await deliver_alert_notification(outbox_sessions, AsyncMock(return_value=True), clock=lambda: now)
        async with outbox_sessions() as db:
            alert = await db.get(Alert, alert_id)
            job = await db.get(NotificationOutbox, job_id)
            assert alert is not None and alert.telegram_notified_at is None
            assert job is not None and job.status == "processing" and job.delivered_at is None

    run(scenario())


def test_retained_reference_does_not_recreate_removed_alert(outbox_sessions):
    async def scenario():
        now = utcnow()
        async with outbox_sessions.begin() as db:
            alert = await seed(db, now)
            alert_id = alert.id
            await enqueue_alert_notification(
                db, NotificationDraft("active", "site", "telegram", "fixture"), (Ref(alert_id, "active"),), now=now
            )
            await db.execute(delete(Alert).where(Alert.id == alert_id))
        assert (
            await deliver_alert_notification(outbox_sessions, AsyncMock(return_value=True), clock=lambda: now) == "sent"
        )
        async with outbox_sessions() as db:
            assert await db.get(Alert, alert_id) is None
            assert await db.scalar(select(func.count()).select_from(NotificationOutboxAlert)) == 1

    run(scenario())


@pytest.mark.parametrize("action", ["resolved", "created"])
def test_non_active_delivery_does_not_set_active_notification_timestamp(outbox_sessions, action):
    async def scenario():
        now = utcnow()
        async with outbox_sessions.begin() as db:
            alert = await seed(db, now)
            alert_id = alert.id
            await enqueue_alert_notification(
                db,
                NotificationDraft(action, "site", "telegram", "fixture"),
                (Ref(alert_id, action),),
                now=now,
            )
        assert (
            await deliver_alert_notification(outbox_sessions, AsyncMock(return_value=True), clock=lambda: now) == "sent"
        )
        async with outbox_sessions() as db:
            alert = await db.get(Alert, alert_id)
            assert alert is not None and alert.telegram_notified_at is None
            assert await db.scalar(select(func.count()).select_from(IncidentTimelineEvent)) == 1

    run(scenario())


def test_expired_ack_never_updates_alert_domain(outbox_sessions):
    async def scenario():
        now = utcnow()
        async with outbox_sessions.begin() as db:
            alert = await seed(db, now)
            alert_id = alert.id
            await enqueue_alert_notification(
                db, NotificationDraft("active", "site", "telegram", "fixture"), (Ref(alert_id, "active"),), now=now
            )
        times = iter([now, now + timedelta(seconds=61)])
        assert (
            await deliver_alert_notification(outbox_sessions, AsyncMock(return_value=True), clock=lambda: next(times))
            == "lease_lost"
        )
        async with outbox_sessions() as db:
            alert = await db.get(Alert, alert_id)
            assert alert is not None and alert.telegram_notified_at is None
            assert await db.scalar(select(func.count()).select_from(IncidentTimelineEvent)) == 0

    run(scenario())


@pytest.mark.parametrize("lock_target", ["domain", "job"])
def test_lock_preparation_cannot_acknowledge_an_expired_lease(outbox_sessions, monkeypatch, lock_target):
    from backend.app.services import alert_notification_outbox_service as service

    from backend.app.repositories.notification_outbox_repository import NotificationOutboxRepository

    target = service if lock_target == "domain" else NotificationOutboxRepository
    attribute = "lock_alert_notification_state" if lock_target == "domain" else "lock_for_acknowledgement"
    original = getattr(target, attribute)

    async def scenario():
        now = utcnow()
        clock = [now]
        async with outbox_sessions.begin() as db:
            alert = await seed(db, now)
            alert_id = alert.id
            job_id = await enqueue_alert_notification(
                db,
                NotificationDraft("lock-expiry", "fixture", "telegram", "fixture"),
                (Ref(alert_id, "active"),),
                now=now,
            )

        async def delayed_lock(db, ids):
            result = await original(db, ids)
            clock[0] += timedelta(seconds=61)
            return result

        monkeypatch.setattr(target, attribute, delayed_lock)
        assert (
            await deliver_alert_notification(outbox_sessions, AsyncMock(return_value=True), clock=lambda: clock[0])
            == "lease_lost"
        )
        async with outbox_sessions() as db:
            job = await db.get(NotificationOutbox, job_id)
            alert = await db.get(Alert, alert_id)
            assert job is not None and job.status == "processing" and job.delivered_at is None
            assert alert is not None and alert.telegram_notified_at is None
            assert await db.scalar(select(func.count()).select_from(IncidentTimelineEvent)) == 0

    run(scenario())
