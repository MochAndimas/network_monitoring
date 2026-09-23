"""Outbox persistence without hidden commits or network I/O."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import uuid
from typing import cast

from sqlalchemy.engine import CursorResult

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..models.notification_outbox import NotificationOutbox as Job
from ..models.notification_outbox_stream import NotificationOutboxStream as Stream


@dataclass(frozen=True)
class NotificationDraft:
    idempotency_key: str
    stream_key: str
    channel: str
    message: str
    destination: str | None = None

    def __post_init__(self) -> None:
        for name, limit in (("idempotency_key", 64), ("stream_key", 128), ("channel", 30)):
            value = getattr(self, name)
            if not value.strip() or len(value) > limit:
                raise ValueError(f"{name} must contain 1..{limit} characters")
        if not self.message.strip():
            raise ValueError("message must not be blank")
        if self.destination is not None and (not self.destination.strip() or len(self.destination) > 255):
            raise ValueError("destination must contain 1..255 characters")


@dataclass(frozen=True)
class ClaimedNotification:
    id: int
    lease_token: str
    channel: str
    message: str
    attempts: int
    destination: str | None = None


class NotificationOutboxRepository:
    """Callers commit enqueue with domain data and claim/ack in short transactions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def lock_streams(self, streams: list[tuple[str, str]]) -> None:
        # This row lock lives until the caller commits/rolls back, so IDs within
        # a stream follow producer commit order, including its first job.
        for channel, stream_key in sorted(set(streams)):
            stream_values = dict(channel=channel, stream_key=stream_key)
            if self.db.get_bind().dialect.name == "mysql":
                statement = mysql_insert(Stream).values(**stream_values)
                await self.db.execute(statement.on_duplicate_key_update(stream_key=Stream.stream_key))
            else:
                await self.db.execute(sqlite_insert(Stream).values(**stream_values).on_conflict_do_nothing())

    async def enqueue(self, draft: NotificationDraft, *, now: datetime) -> int:
        await self.lock_streams([(draft.channel, draft.stream_key)])
        # Avoid a missing-key gap lock here. If the snapshot misses a concurrent
        # winner, the atomic insert below and subsequent current read recover it.
        query = select(Job).where(Job.idempotency_key == draft.idempotency_key)
        row = await self.db.scalar(query)
        if row is None:
            values = dict(
                idempotency_key=draft.idempotency_key,
                stream_key=draft.stream_key,
                channel=draft.channel,
                message=draft.message,
                destination=draft.destination,
                status="pending",
                attempts=0,
                available_at=now,
                created_at=now,
                updated_at=now,
            )
            if self.db.get_bind().dialect.name == "mysql":
                statement = mysql_insert(Job).values(**values)
                await self.db.execute(statement.on_duplicate_key_update(idempotency_key=Job.idempotency_key))
            else:
                await self.db.execute(
                    sqlite_insert(Job).values(**values).on_conflict_do_nothing(index_elements=["idempotency_key"])
                )
            # A concurrent winner may not be in this transaction's earlier read view.
            row = await self.db.scalar(query.with_for_update().execution_options(populate_existing=True))
        if row is None:
            raise RuntimeError("Outbox enqueue did not produce a row")
        if (row.stream_key, row.channel, row.message, row.destination) != (
            draft.stream_key,
            draft.channel,
            draft.message,
            draft.destination,
        ):
            raise ValueError("Idempotency key already belongs to a different notification")
        return row.id

    async def claim_next(
        self,
        *,
        channel: str,
        now: datetime,
        lease_seconds: int,
        max_attempts: int,
    ) -> ClaimedNotification | None:
        if lease_seconds <= 0 or max_attempts <= 0:
            raise ValueError("Lease duration and attempt limit must be positive")
        previous = aliased(Job)
        # Failed/exhausted predecessors also block a stream: a resolution must
        # not overtake an undelivered active notification. Other streams proceed.
        predecessor = exists(
            select(previous.id).where(
                previous.stream_key == Job.stream_key,
                previous.channel == Job.channel,
                previous.id < Job.id,
                previous.status != "sent",
            )
        )
        ready = or_(
            and_(Job.status == "pending", Job.available_at <= now),
            and_(Job.status == "processing", Job.lease_until <= now),
        )
        # Discover a bounded window without locking the scan/sort. Then lock
        # only one primary-key row; a filesort FOR UPDATE can otherwise lock
        # unrelated streams and make a second SKIP LOCKED worker appear idle.
        candidate_ids = list(
            (
                await self.db.scalars(
                    select(Job.id)
                    .where(Job.channel == channel, ready, ~predecessor)
                    .order_by(Job.available_at, Job.id)
                    .limit(32)
                )
            ).all()
        )
        # Sent is terminal, so the predecessor eligibility check above cannot
        # become false for already committed jobs. Keep its subquery out of this
        # locking read: MySQL may lock rows read by an optimized anti-join.
        row = None
        for candidate_id in candidate_ids:
            row = await self.db.scalar(
                select(Job)
                .where(Job.id == candidate_id, ready)
                .with_hint(Job, "FORCE INDEX (PRIMARY)", dialect_name="mysql")
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
            if row is not None:
                break
        if row is None:
            return None
        if row.attempts >= max_attempts:
            await self.db.execute(
                update(Job)
                .where(Job.id == row.id, ready)
                .values(
                    status="dead",
                    lease_token=None,
                    lease_until=None,
                    last_error="attempts_exhausted",
                    updated_at=now,
                )
            )
            return None
        token = uuid.uuid4().hex
        attempts = row.attempts + 1
        result = await self.db.execute(
            update(Job)
            .where(Job.id == row.id, ready)
            .values(
                status="processing",
                lease_token=token,
                lease_until=now + timedelta(seconds=lease_seconds),
                attempts=attempts,
                updated_at=now,
            )
        )
        if cast(CursorResult, result).rowcount != 1:
            return None
        return ClaimedNotification(row.id, token, row.channel, row.message, attempts, row.destination)

    async def lock_for_acknowledgement(self, claim: ClaimedNotification) -> None:
        """Finish any job-lock wait before the service samples the lease clock."""
        await self.db.execute(select(Job.id).where(Job.id == claim.id).with_for_update())

    async def acknowledge(
        self,
        claim: ClaimedNotification,
        *,
        now: datetime,
        delivered: bool,
        max_attempts: int,
        retry_seconds: int,
    ) -> bool:
        if max_attempts <= 0 or retry_seconds < 0:
            raise ValueError("Invalid retry policy")
        terminal = claim.attempts >= max_attempts
        result = await self.db.execute(
            update(Job)
            .where(
                Job.id == claim.id,
                Job.status == "processing",
                Job.lease_token == claim.lease_token,
                Job.lease_until > now,
            )
            .values(
                status="sent" if delivered else ("dead" if terminal else "pending"),
                delivered_at=now if delivered else None,
                updated_at=now,
                available_at=now + timedelta(seconds=retry_seconds),
                lease_until=None,
                lease_token=None,
                last_error=None if delivered else "delivery_failed",
            )
        )
        return cast(CursorResult, result).rowcount == 1
