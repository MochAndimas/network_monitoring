"""Queue health boundaries, persistent visibility, and safe metric cardinality."""

from dataclasses import asdict
from datetime import datetime, timedelta

from sqlalchemy import event

from backend.app.models.notification_outbox import NotificationOutbox as Job
from backend.app.services.notification_outbox_health import (
    NotificationQueueHealth,
    build_notification_queue_health,
    render_notification_queue_metrics,
)
from tests.test_utils import run


def test_queue_health_counts_committed_jobs_without_payload_reads(outbox_sessions):
    async def scenario():
        now = datetime(2026, 9, 9, 12)
        async with outbox_sessions.begin() as db:
            for index, (status, due, lease, channel) in enumerate(
                [
                    ("dead", -1, None, "telegram"),
                    ("pending", 0, None, "telegram"),
                    ("pending", 1, None, "telegram"),
                    ("processing", -1, 0, "telegram"),
                    ("processing", -1, 1, "telegram"),
                    ("processing", -1, None, "telegram"),
                    ("sent", -1, None, "telegram"),
                    ("pending", -1, None, "other"),
                ]
            ):
                db.add(
                    Job(
                        idempotency_key=str(index),
                        stream_key="same-stream",
                        channel=channel,
                        status=status,
                        message="private-message",
                        destination="private-destination",
                        created_at=now - timedelta(seconds=60),
                        updated_at=now,
                        available_at=now + timedelta(seconds=due),
                        lease_until=None if lease is None else now + timedelta(seconds=lease),
                    )
                )
        statements = []

        def record(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        async with outbox_sessions() as db:
            engine = db.get_bind()
            event.listen(engine, "before_cursor_execute", record)
            try:
                health = await build_notification_queue_health(db, now=now)
            finally:
                event.remove(engine, "before_cursor_execute", record)
        assert health == NotificationQueueHealth(2, 3, 1, 1, 1, 60, 60, 60)
        assert len(statements) == 1
        assert "message" not in statements[0] and "destination" not in statements[0]
        assert "FOR UPDATE" not in statements[0]
        # The due job sits behind a dead job in this stream;
        # this field intentionally reports timestamps, not claim eligibility.
        metrics = render_notification_queue_metrics(health)
        assert 'network_monitoring_notification_outbox_jobs{channel="telegram",status="dead"} 1' in metrics
        assert 'network_monitoring_notification_outbox_due_pending{channel="telegram"} 1' in metrics
        assert 'network_monitoring_notification_outbox_expired_leases{channel="telegram"} 1' in metrics
        assert "private-" not in metrics and "same-stream" not in metrics
        assert len([line for line in metrics.splitlines() if not line.startswith("#")]) == 8

    run(scenario())


def test_empty_queue_resets_every_gauge(outbox_sessions):
    async def scenario():
        async with outbox_sessions() as db:
            health = await build_notification_queue_health(db, now=datetime(2026, 9, 9))
        assert all(value == 0 for value in asdict(health).values())
        assert (
            len([line for line in render_notification_queue_metrics(health).splitlines() if not line.startswith("#")])
            == 8
        )

    run(scenario())


def test_future_creation_does_not_produce_negative_queue_age(outbox_sessions):
    async def scenario():
        now = datetime(2026, 9, 9)
        async with outbox_sessions.begin() as db:
            db.add(
                Job(
                    idempotency_key="future",
                    stream_key="future",
                    channel="telegram",
                    message="fixture",
                    status="pending",
                    created_at=now + timedelta(seconds=1),
                    available_at=now,
                    updated_at=now,
                )
            )
        async with outbox_sessions() as db:
            health = await build_notification_queue_health(db, now=now)
        assert health.pending == 1
        assert health.oldest_pending_age_seconds == 0

    run(scenario())
