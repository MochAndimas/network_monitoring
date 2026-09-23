"""Read-only aggregates over unfinished jobs, without loading notification payloads."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.notification_outbox import NotificationOutbox as Job


@dataclass(frozen=True)
class NotificationQueueState:
    status: str
    jobs: int
    oldest_created_at: datetime | None
    due_pending: int
    expired_leases: int


async def read_notification_queue(db: AsyncSession, *, channel: str, now: datetime) -> list[NotificationQueueState]:
    """One aggregate query; due timestamps do not imply FIFO claim eligibility."""
    rows = (
        await db.execute(
            select(
                Job.status,
                func.count(Job.id),
                func.min(Job.created_at),
                func.sum(case(((Job.status == "pending") & (Job.available_at <= now), 1), else_=0)),
                func.sum(case(((Job.status == "processing") & (Job.lease_until <= now), 1), else_=0)),
            )
            .where(Job.channel == channel, Job.status.in_(("pending", "processing", "dead")))
            .group_by(Job.status)
        )
    ).all()
    return [
        NotificationQueueState(status, int(count), oldest, int(due), int(expired))
        for status, count, oldest, due, expired in rows
    ]
