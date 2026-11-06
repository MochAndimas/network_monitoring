from sqlalchemy import select

from backend.app.models.notification_outbox import NotificationOutbox
from backend.app.notifications.smoke_test import enqueue_test
from tests.test_utils import run


def test_operator_test_is_committed_pending_and_addressed(outbox_sessions):
    async def scenario():
        first = await enqueue_test(outbox_sessions, "test-destination")
        second = await enqueue_test(outbox_sessions, "test-destination")
        async with outbox_sessions() as db:
            rows = list((await db.scalars(select(NotificationOutbox).order_by(NotificationOutbox.id))).all())
        assert first != second
        assert len(rows) == 2
        for row in rows:
            assert row.status == "pending"
            assert row.channel == "telegram"
            assert row.destination == "test-destination"
            assert row.message.startswith("[TEST]")
            assert "bukan insiden" in row.message
            assert row.attempts == 0
    run(scenario())


def test_operator_test_finishes_and_preserves_already_sent_part(outbox_sessions):
    from unittest.mock import AsyncMock
    from backend.app.services.alert_notification_outbox_service import deliver_alert_notification

    async def scenario():
        job_id = await enqueue_test(outbox_sessions, "test-destination")
        async with outbox_sessions.begin() as db:
            row = await db.get(NotificationOutbox, job_id)
            row.next_part = 1  # Existing production test already sent its only part.
        sender = AsyncMock(return_value=True)
        assert await deliver_alert_notification(outbox_sessions, sender, routed_sender=sender) == "sent"
        sender.assert_not_awaited()
        async with outbox_sessions() as db:
            row = await db.get(NotificationOutbox, job_id)
            assert row.status == "sent"
            assert row.next_part == 1
            assert row.last_error is None
    run(scenario())


def test_new_operator_test_uses_real_delivery_acknowledgement(outbox_sessions):
    from unittest.mock import AsyncMock
    from backend.app.services.alert_notification_outbox_service import deliver_alert_notification

    async def scenario():
        job_id = await enqueue_test(outbox_sessions, "test-destination")
        sender = AsyncMock(return_value=True)
        assert await deliver_alert_notification(outbox_sessions, sender, routed_sender=sender) == "sent"
        sender.assert_awaited_once()
        async with outbox_sessions() as db:
            assert (await db.get(NotificationOutbox, job_id)).status == "sent"
    run(scenario())


def test_missing_alert_references_are_still_rejected_for_other_jobs(outbox_sessions):
    import pytest
    from unittest.mock import AsyncMock
    from backend.app.services.alert_notification_outbox_service import deliver_alert_notification

    async def scenario():
        job_id = await enqueue_test(outbox_sessions, "test-destination")
        async with outbox_sessions.begin() as db:
            row = await db.get(NotificationOutbox, job_id)
            row.idempotency_key = "ordinary-alert"
            row.next_part = 1
        sender = AsyncMock(return_value=True)
        with pytest.raises(RuntimeError, match="no domain references"):
            await deliver_alert_notification(outbox_sessions, sender, routed_sender=sender)
        async with outbox_sessions() as db:
            assert (await db.get(NotificationOutbox, job_id)).status != "sent"
    run(scenario())
