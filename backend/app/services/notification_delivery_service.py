"""Deliver a single committed outbox job outside every database transaction.

This infrastructure is not registered with the scheduler until alert policies
and delivery acknowledgements have been integrated.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..core.time import utcnow
from ..repositories.notification_outbox_repository import ClaimedNotification, NotificationOutboxRepository

NotificationSender = Callable[[str], Awaitable[bool]]
RoutedNotificationSender = Callable[[str, str], Awaitable[bool]]
DeliveryAcknowledgement = Callable[[AsyncSession, ClaimedNotification, datetime], Awaitable[None]]
AcknowledgementPreparation = Callable[[AsyncSession, ClaimedNotification], Awaitable[None]]


@dataclass(frozen=True)
class DeliveryPolicy:
    lease_seconds: int = 60
    send_timeout_seconds: int = 20
    max_attempts: int = 5
    retry_base_seconds: int = 5
    retry_max_seconds: int = 300

    def __post_init__(self) -> None:
        if self.send_timeout_seconds <= 0 or self.lease_seconds <= self.send_timeout_seconds:
            raise ValueError("Lease must exceed a positive delivery timeout")
        if self.max_attempts <= 0 or not 0 < self.retry_base_seconds <= self.retry_max_seconds:
            raise ValueError("Invalid attempt/backoff limits")

    def retry_seconds(self, attempts: int) -> int:
        return min(self.retry_base_seconds * (1 << min(max(attempts - 1, 0), 30)), self.retry_max_seconds)


async def deliver_one(
    sessions: async_sessionmaker[AsyncSession],
    sender: NotificationSender,
    *,
    channel: str = "telegram",
    policy: DeliveryPolicy = DeliveryPolicy(),
    clock: Callable[[], datetime] = utcnow,
    on_delivered: DeliveryAcknowledgement | None = None,
    routed_sender: RoutedNotificationSender | None = None,
    before_acknowledge: AcknowledgementPreparation | None = None,
) -> str:
    """Return idle/sent/retry/dead/lease_lost; never send while holding a DB session."""
    async with sessions.begin() as db:
        claim = await NotificationOutboxRepository(db).claim_next(
            channel=channel,
            now=clock(),
            lease_seconds=policy.lease_seconds,
            max_attempts=policy.max_attempts,
        )
    if claim is None:
        return "idle"
    try:
        if claim.destination is not None:
            if routed_sender is None:
                raise RuntimeError("A routed job requires a destination-aware sender")
            delivery = routed_sender(claim.destination, claim.message)
        else:
            delivery = sender(claim.message)
        delivered = await asyncio.wait_for(delivery, timeout=policy.send_timeout_seconds)
    except Exception:
        # Exception bodies can contain provider credentials. Persist only a category.
        delivered = False
    # Cancellation intentionally leaves the lease recoverable after its deadline.
    async with sessions.begin() as db:
        if delivered and before_acknowledge is not None:
            await before_acknowledge(db, claim)
        repository = NotificationOutboxRepository(db)
        await repository.lock_for_acknowledgement(claim)
        # Lock contention may have consumed the remaining lease. Check using
        # the time after preparation, never the time before waiting for locks.
        acknowledged_at = clock()
        accepted = await repository.acknowledge(
            claim,
            now=acknowledged_at,
            delivered=delivered,
            max_attempts=policy.max_attempts,
            retry_seconds=policy.retry_seconds(claim.attempts),
        )
        if accepted and delivered and on_delivered is not None:
            await on_delivered(db, claim, acknowledged_at)
    if not accepted:
        return "lease_lost"
    return "sent" if delivered else ("dead" if claim.attempts >= policy.max_attempts else "retry")
