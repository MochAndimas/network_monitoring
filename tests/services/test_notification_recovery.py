from datetime import timedelta
from unittest.mock import AsyncMock

from sqlalchemy import select
from telegram.error import Forbidden

from backend.app.core.time import utcnow
from backend.app.models.notification_outbox import NotificationOutbox as Job
from backend.app.repositories.notification_outbox_repository import NotificationDraft, NotificationOutboxRepository
from backend.app.services.notification_delivery_service import DeliveryPolicy, deliver_one
from backend.app.services.notification_maintenance import recover_failed_notifications
from tests.test_utils import run


def test_cooldown_recovery_unblocks_stream_and_preserves_multipart_cursor(outbox_sessions):
    async def scenario():
        now = utcnow()
        async with outbox_sessions.begin() as db:
            repo = NotificationOutboxRepository(db)
            first = await repo.enqueue(NotificationDraft("first", "site", "telegram", "first", "123"), now=now)
            second = await repo.enqueue(NotificationDraft("second", "site", "telegram", "second", "123"), now=now)
        assert await deliver_one(outbox_sessions, AsyncMock(return_value=False), routed_sender=AsyncMock(side_effect=Forbidden("private-token")), policy=DeliveryPolicy(max_attempts=1), clock=lambda: now) == "dead"
        async with outbox_sessions.begin() as db:
            row = await db.get(Job, first)
            assert row.last_error == "forbidden"
            row.next_part = 1
            assert await recover_failed_notifications(db, now=now + timedelta(seconds=299)) == 0
        assert await deliver_one(outbox_sessions, AsyncMock(return_value=True), clock=lambda: now) == "idle"
        async with outbox_sessions.begin() as db:
            assert await recover_failed_notifications(db, now=now + timedelta(minutes=5)) == 1
        async with outbox_sessions() as db:
            row = await db.get(Job, first)
            assert (row.status, row.attempts, row.next_part, row.destination, row.last_error) == ("pending", 0, 1, "123", "forbidden")
        clock = lambda: now + timedelta(minutes=5)
        sender = AsyncMock(return_value=True)
        assert await deliver_one(outbox_sessions, sender, routed_sender=sender, clock=clock) == "sent"
        assert sender.call_count == 0  # Already-delivered multipart part is not repeated.
        assert await deliver_one(outbox_sessions, sender, routed_sender=sender, clock=clock) == "sent"
        async with outbox_sessions() as db:
            assert (await db.get(Job, second)).status == "sent"
            assert await db.scalar(select(Job.last_error).where(Job.id == first)) is None
    run(scenario())
