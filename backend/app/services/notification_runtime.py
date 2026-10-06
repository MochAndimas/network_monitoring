"""Own a delivery runner and a persistent heartbeat for its full lifecycle."""

import asyncio
import uuid
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ..core.time import utcnow
from .notification_delivery_service import DeliveryPolicy, RoutedNotificationSender
from .notification_maintenance import record_worker_heartbeat, retain_notifications
from .notification_worker import NotificationWorkerPolicy, NotificationWorkerReport, run_alert_notification_worker


async def reject_legacy_message(message: str) -> bool:
    """A legacy job without a destination must be reconciled explicitly."""
    return False


async def run_notification_runtime(
    sessions: async_sessionmaker[AsyncSession],
    sender: RoutedNotificationSender,
    stop: asyncio.Event,
    *,
    worker_id: str | None = None,
    heartbeat_seconds: float = 10,
    worker_policy: NotificationWorkerPolicy = NotificationWorkerPolicy(),
    delivery_policy: DeliveryPolicy = DeliveryPolicy(),
) -> NotificationWorkerReport:
    if not 0 < heartbeat_seconds <= 30:
        raise ValueError("Heartbeat interval must be within 30 seconds")
    identity = worker_id or uuid.uuid4().hex

    async def heartbeat() -> None:
        cycle = 0
        while not stop.is_set():
            async with sessions.begin() as db:
                await record_worker_heartbeat(db, worker_id=identity, status="running", now=utcnow())
                if cycle % 360 == 0:
                    await retain_notifications(db, now=utcnow())
            cycle += 1
            try:
                await asyncio.wait_for(stop.wait(), heartbeat_seconds)
            except TimeoutError:
                pass

    async with sessions.begin() as db:
        await record_worker_heartbeat(db, worker_id=identity, status="running", now=utcnow())
    delivery = asyncio.create_task(
        run_alert_notification_worker(
            sessions,
            reject_legacy_message,
            stop,
            routed_sender=sender,
            worker_policy=worker_policy,
            delivery_policy=delivery_policy,
        )
    )
    pulse = asyncio.create_task(heartbeat())
    try:
        done, _ = await asyncio.wait({delivery, pulse}, return_when=asyncio.FIRST_COMPLETED)
        # A heartbeat database failure is fatal: never report a healthy process
        # whose lifecycle supervision has silently stopped.
        for task in done:
            task.result()
        stop.set()
        return await delivery
    finally:
        stop.set()
        await asyncio.gather(delivery, return_exceptions=True)
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)
        async with sessions.begin() as db:
            await record_worker_heartbeat(db, worker_id=identity, status="stopped", now=utcnow())
