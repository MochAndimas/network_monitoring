"""Bounded worker lifecycle; transport, sessions, and shutdown are injected."""

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
import logging
import math

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..core.time import utcnow
from .alert_notification_outbox_service import deliver_alert_notification
from .notification_delivery_service import DeliveryPolicy, NotificationSender, RoutedNotificationSender

logger = logging.getLogger("network_monitoring.notification_worker")
_OUTCOMES = {"idle", "sent", "retry", "dead", "lease_lost"}


@dataclass(frozen=True)
class NotificationWorkerPolicy:
    concurrency: int = 2
    poll_seconds: float = 1.0
    error_backoff_seconds: float = 5.0
    shutdown_grace_seconds: float = 25.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.concurrency, bool)
            or not isinstance(self.concurrency, int)
            or not 1 <= self.concurrency <= 16
        ):
            raise ValueError("Worker concurrency must be an integer in 1..16")
        durations = (self.poll_seconds, self.error_backoff_seconds, self.shutdown_grace_seconds)
        if any(not math.isfinite(value) or value < 0.01 for value in durations):
            raise ValueError("Worker durations must be finite and at least 0.01 seconds")
        if self.error_backoff_seconds < self.poll_seconds:
            raise ValueError("Error backoff must be at least the polling interval")


@dataclass(frozen=True)
class NotificationWorkerReport:
    sent: int
    retries: int
    dead: int
    lease_lost: int
    errors: int
    idle_polls: int
    cancelled_lanes: int


async def _wait_for_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def run_notification_worker(
    deliver: Callable[[], Awaitable[str]],
    stop: asyncio.Event,
    *,
    policy: NotificationWorkerPolicy = NotificationWorkerPolicy(),
) -> NotificationWorkerReport:
    """Drain in-flight deliveries on stop, then cancel after the grace deadline.

    Parent cancellation immediately cancels and joins every lane. Cancellation
    leaves delivery leases recoverable; no detached background tasks survive.
    Counts describe this run only, not the durable queue or fleet-wide metrics.
    """
    counts: Counter[str] = Counter()
    cancelled_lanes = 0

    async def lane() -> None:
        while not stop.is_set():
            try:
                outcome = await deliver()
                if outcome not in _OUTCOMES:
                    raise ValueError("Unknown notification delivery outcome")
            except Exception:
                counts["errors"] += 1
                # Provider/DB exception text can contain credentials. Report a
                # fixed category; preserve detailed diagnostics at safe sources.
                logger.warning("Notification worker iteration failed; category=delivery_error")
                await _wait_for_stop(stop, policy.error_backoff_seconds)
                continue
            counts[outcome] += 1
            if outcome in {"idle", "lease_lost"}:
                await _wait_for_stop(stop, policy.poll_seconds)
            else:
                await asyncio.sleep(0)  # Fair scheduling even with an immediate sender.

    if not stop.is_set():
        lanes = [asyncio.create_task(lane(), name=f"notification-worker-{i}") for i in range(policy.concurrency)]
        stopped = asyncio.create_task(stop.wait(), name="notification-worker-stop")
        try:
            await asyncio.wait([stopped, *lanes], return_when=asyncio.FIRST_COMPLETED)
            if not stop.is_set():
                raise RuntimeError("Notification worker lane stopped unexpectedly")
            _, pending = await asyncio.wait(lanes, timeout=policy.shutdown_grace_seconds)
            cancelled_lanes = len(pending)
        finally:
            for task in [stopped, *lanes]:
                if not task.done():
                    task.cancel()
            await asyncio.gather(stopped, *lanes, return_exceptions=True)
    return NotificationWorkerReport(
        counts["sent"],
        counts["retry"],
        counts["dead"],
        counts["lease_lost"],
        counts["errors"],
        counts["idle"],
        cancelled_lanes,
    )


async def run_alert_notification_worker(
    sessions: async_sessionmaker[AsyncSession],
    sender: NotificationSender,
    stop: asyncio.Event,
    *,
    routed_sender: RoutedNotificationSender | None = None,
    worker_policy: NotificationWorkerPolicy = NotificationWorkerPolicy(),
    delivery_policy: DeliveryPolicy = DeliveryPolicy(),
    clock: Callable[[], datetime] = utcnow,
) -> NotificationWorkerReport:
    """Bind every iteration to atomic alert/incident acknowledgement."""

    async def deliver() -> str:
        return await deliver_alert_notification(
            sessions,
            sender,
            routed_sender=routed_sender,
            policy=delivery_policy,
            clock=clock,
        )

    return await run_notification_worker(deliver, stop, policy=worker_policy)
