"""Explicit failed-job recovery and bounded retention of completed lifecycles."""

from datetime import datetime, timedelta
from sqlalchemy import delete, exists, select, update
from sqlalchemy.orm import aliased
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from typing import cast
from ..models.alert import Alert
from ..models.notification_outbox import NotificationOutbox as Job
from ..models.notification_outbox_alert import NotificationOutboxAlert as Reference
from ..models.notification_worker import NotificationWorker


async def redrive_notification(db: AsyncSession, job_id: int, *, now: datetime) -> bool:
    """Preserve payload, route, ordering and multipart cursor; sent is terminal."""
    result = await db.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == "dead")
        .values(
            status="pending",
            attempts=0,
            available_at=now,
            updated_at=now,
            lease_token=None,
            lease_until=None,
            last_error=None,
        )
    )
    return cast(CursorResult, result).rowcount == 1


async def retain_notifications(db: AsyncSession, *, now: datetime, days: int = 30, batch_size: int = 250) -> int:
    """Keep unfinished streams and live/recent alert correlation identities intact."""
    if days < 1 or not 1 <= batch_size <= 1000:
        raise ValueError("Invalid notification retention policy")
    cutoff = now - timedelta(days=days)
    other = aliased(Job)
    unfinished = exists(
        select(other.id).where(other.channel == Job.channel, other.stream_key == Job.stream_key, other.status != "sent")
    )
    live_reference = exists(
        select(Reference.alert_id)
        .join(Alert, Alert.id == Reference.alert_id)
        .where(
            Reference.outbox_id == Job.id,
            (Alert.status == "active") | (Alert.resolved_at >= cutoff),
        )
    )
    ids = list(
        (
            await db.scalars(
                select(Job.id)
                .where(
                    Job.status == "sent",
                    Job.delivered_at < cutoff,
                    ~unfinished,
                    ~live_reference,
                )
                .order_by(Job.id)
                .limit(batch_size)
            )
        ).all()
    )
    if ids:
        # Explicit reference removal also supports SQLite fixtures without FK enforcement.
        await db.execute(delete(Reference).where(Reference.outbox_id.in_(ids)))
        await db.execute(delete(Job).where(Job.id.in_(ids), Job.status == "sent"))
    await db.execute(delete(NotificationWorker).where(NotificationWorker.updated_at < cutoff))
    return len(ids)


async def record_worker_heartbeat(db: AsyncSession, *, worker_id: str, status: str, now: datetime) -> None:
    worker = await db.get(NotificationWorker, worker_id)
    if worker is None:
        db.add(NotificationWorker(worker_id=worker_id, status=status, updated_at=now))
    else:
        worker.status, worker.updated_at = status, now
    await db.flush()
