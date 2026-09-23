"""Snapshot routing and grouped enqueue through the real writer."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from backend.app.core.time import utcnow
from backend.app.models import Alert, Device, NotificationOutbox, NotificationOutboxAlert
from backend.app.services.telegram_outbox_writer import TelegramOutboxWriter
from backend.app.services.alert_notification_outbox_service import deliver_alert_notification
from tests.test_utils import run


async def events(db):
    device = Device(name="Fixture", ip_address="10.175.0.1", site="fixture", device_type="switch")
    db.add(device)
    await db.flush()
    result = []
    for alert_type in ("device_down", "high_packet_loss_critical"):
        alert = Alert(
            device_id=device.id,
            alert_type=alert_type,
            severity="critical",
            message="Fixture",
            status="active",
            created_at=utcnow() - timedelta(hours=1),
        )
        db.add(alert)
        await db.flush()
        result.append(
            dict(
                alert=alert,
                alert_id=alert.id,
                alert_type=alert.alert_type,
                action="active",
                device=device,
                severity="critical",
                message=alert.message,
            )
        )
    return result


def test_grouping_repeat_enqueue_and_routed_delivery(outbox_sessions):
    async def scenario():
        writer = TelegramOutboxWriter("-100123")
        async with outbox_sessions.begin() as db:
            batch = await events(db)
            await writer(db, list(reversed(batch)))
            await writer(db, batch + batch)
            assert await db.scalar(select(func.count()).select_from(NotificationOutbox)) == 1
            assert await db.scalar(select(func.count()).select_from(NotificationOutboxAlert)) == 2
            assert all(item["alert"].telegram_notified_at is None for item in batch)
        routed = AsyncMock(return_value=True)
        legacy = AsyncMock(side_effect=AssertionError("Must not use current configuration"))
        assert await deliver_alert_notification(outbox_sessions, legacy, routed_sender=routed) == "sent"
        legacy.assert_not_awaited()
        assert routed.call_args.args[0] == "-100123"
        assert "device_down" in routed.call_args.args[1]
        assert "high_packet_loss_critical" in routed.call_args.args[1]

    run(scenario())


def test_routed_job_cannot_fall_back_to_legacy_sender(outbox_sessions):
    async def scenario():
        async with outbox_sessions.begin() as db:
            await TelegramOutboxWriter("123")(db, await events(db))
        legacy = AsyncMock(return_value=True)
        assert await deliver_alert_notification(outbox_sessions, legacy) == "retry"
        legacy.assert_not_awaited()

    run(scenario())


def test_active_and_resolved_keep_same_stream_and_order(outbox_sessions):
    async def scenario():
        writer = TelegramOutboxWriter("123")
        async with outbox_sessions.begin() as db:
            batch = await events(db)
            await writer(db, batch)
            for item in batch:
                item["alert"].status = "resolved"
                item["alert"].resolved_at = utcnow()
                item.update(
                    action="resolved", created_at=item["alert"].created_at, resolved_at=item["alert"].resolved_at
                )
            await writer(db, batch)
            await writer(db, list(reversed(batch)))
            jobs = list((await db.scalars(select(NotificationOutbox).order_by(NotificationOutbox.id))).all())
            assert len(jobs) == 2 and jobs[0].stream_key == jobs[1].stream_key
        routed = AsyncMock(return_value=True)
        for _ in range(2):
            assert await deliver_alert_notification(outbox_sessions, AsyncMock(), routed_sender=routed) == "sent"
        assert "ALERT ACTIVE" in routed.call_args_list[0].args[1]
        assert "ALERT RESOLVED" in routed.call_args_list[1].args[1]

    run(scenario())


def test_changed_route_cannot_bypass_pending_active(outbox_sessions):
    async def scenario():
        async with outbox_sessions.begin() as db:
            batch = await events(db)
            await TelegramOutboxWriter("123")(db, batch)
        with pytest.raises(ValueError, match="different routing"):
            async with outbox_sessions.begin() as db:
                for item in batch:
                    item["action"] = "resolved"
                await TelegramOutboxWriter("456")(db, batch)
        async with outbox_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(NotificationOutbox)) == 1

    run(scenario())


def test_oversized_message_rolls_back_domain_and_queue(outbox_sessions):
    async def scenario():
        with pytest.raises(ValueError, match="message limit"):
            async with outbox_sessions.begin() as db:
                batch = await events(db)
                batch[0]["message"] = "x" * 4097
                await TelegramOutboxWriter("123")(db, batch)
        async with outbox_sessions() as db:
            for model in (Alert, NotificationOutbox):
                assert await db.scalar(select(func.count()).select_from(model)) == 0

    run(scenario())


@pytest.mark.parametrize("destination", ["", "@mutable_name", "https://example.com", "0" * 21])
def test_writer_rejects_unstable_or_invalid_destination(destination):
    with pytest.raises(ValueError, match="numeric chat ID"):
        TelegramOutboxWriter(destination)


def test_engine_enqueues_resolution_using_real_adapter(outbox_sessions, monkeypatch):
    from backend.app.alerting import engine as engine_facade
    from backend.app.alerting.engine_parts import impl

    monkeypatch.setattr(impl, "_expected_alert_map", AsyncMock(return_value={}))
    direct_sender = AsyncMock(side_effect=AssertionError("Unexpected direct transport"))
    monkeypatch.setattr(engine_facade, "send_telegram_alert", direct_sender)

    async def scenario():
        writer = TelegramOutboxWriter("123")
        async with outbox_sessions.begin() as db:
            await writer(db, await events(db))
        async with outbox_sessions.begin() as db:
            await engine_facade.evaluate_alerts(db, commit=False, notification_writer=writer)
        async with outbox_sessions() as db:
            jobs = list((await db.scalars(select(NotificationOutbox).order_by(NotificationOutbox.id))).all())
            assert len(jobs) == 2 and jobs[0].stream_key == jobs[1].stream_key
            assert "ALERT RESOLVED" in jobs[1].message
            assert (await db.scalars(select(Alert.status))).all() == ["resolved", "resolved"]
        direct_sender.assert_not_awaited()

    run(scenario())


def test_large_group_splits_into_stable_jobs_with_separate_ack(outbox_sessions):
    async def scenario():
        writer = TelegramOutboxWriter("123")
        async with outbox_sessions.begin() as db:
            batch = await events(db)
            for item in batch:
                item["message"] = "😀" * 1200
            await writer(db, batch)
            await writer(db, list(reversed(batch)))
            jobs = list((await db.scalars(select(NotificationOutbox).order_by(NotificationOutbox.id))).all())
            assert len(jobs) == 2
            assert len({job.idempotency_key for job in jobs}) == 2
            assert jobs[0].stream_key == jobs[1].stream_key
            assert all(len(job.message.encode("utf-16-le")) // 2 <= 4096 for job in jobs)
            assert await db.scalar(select(func.count()).select_from(NotificationOutboxAlert)) == 2
        sender = AsyncMock(return_value=True)
        assert await deliver_alert_notification(outbox_sessions, AsyncMock(), routed_sender=sender) == "sent"
        async with outbox_sessions() as db:
            notified = list((await db.scalars(select(Alert.telegram_notified_at))).all())
            assert sum(value is not None for value in notified) == 1
        # Re-evaluation may still carry stale ORM objects from before delivery.
        async with outbox_sessions.begin() as db:
            await writer(db, batch)
            assert await db.scalar(select(func.count()).select_from(NotificationOutbox)) == 2
        assert await deliver_alert_notification(outbox_sessions, AsyncMock(), routed_sender=sender) == "sent"
        async with outbox_sessions() as db:
            assert all(value is not None for value in (await db.scalars(select(Alert.telegram_notified_at))).all())
        assert await deliver_alert_notification(outbox_sessions, AsyncMock(), routed_sender=sender) == "idle"
        async with outbox_sessions.begin() as db:
            await writer(db, batch)
            assert await db.scalar(select(func.count()).select_from(NotificationOutbox)) == 2

    run(scenario())


@pytest.mark.parametrize("changed", [False, True])
def test_reminder_requires_unchanged_delivery_generation(outbox_sessions, changed):
    from sqlalchemy import update

    async def scenario():
        baseline = utcnow() - timedelta(hours=2)
        async with outbox_sessions.begin() as db:
            batch = await events(db)
            for item in batch:
                item["alert"].telegram_notified_at = baseline
                item["action"] = "active_reminder"
        if changed:
            async with outbox_sessions.begin() as db:
                await db.execute(update(Alert).values(telegram_notified_at=baseline + timedelta(hours=1)))
        async with outbox_sessions.begin() as db:
            await TelegramOutboxWriter("123")(db, batch)
            await TelegramOutboxWriter("123")(db, batch)
            assert await db.scalar(select(func.count()).select_from(NotificationOutbox)) == (0 if changed else 1)

    run(scenario())
