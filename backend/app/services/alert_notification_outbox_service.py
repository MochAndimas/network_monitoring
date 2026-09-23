"""Transactional boundary between queued notification jobs and alert delivery state."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..core.time import utcnow
from ..models.alert import Alert
from ..models.notification_outbox import NotificationOutbox as Job
from ..models.notification_outbox_alert import NotificationOutboxAlert as Reference
from ..repositories.incident_repository import IncidentRepository
from ..repositories.notification_outbox_repository import (
    ClaimedNotification,
    NotificationDraft,
    NotificationOutboxRepository,
)
from .notification_delivery_service import DeliveryPolicy, NotificationSender, RoutedNotificationSender, deliver_one

NotificationAction = Literal["active", "active_reminder", "summary_active", "created", "resolved"]
_ACTIVE_ACTIONS = {"active", "active_reminder", "summary_active"}


@dataclass(frozen=True)
class AlertNotificationState:
    status: str
    notified_at: datetime | None
    resolved_at: datetime | None


async def lock_alert_notification_state(db: AsyncSession, alert_ids: set[int]) -> dict[int, AlertNotificationState]:
    """Acquire domain rows before stream/job locks, with a current column read."""
    ordered = sorted(alert_ids)
    states = {}
    for offset in range(0, len(ordered), 500):
        rows = await db.execute(
            select(Alert.id, Alert.status, Alert.telegram_notified_at, Alert.resolved_at)
            .where(Alert.id.in_(ordered[offset : offset + 500]))
            .order_by(Alert.id)
            .with_for_update()
        )
        for alert_id, status, notified_at, resolved_at in rows:
            states[alert_id] = AlertNotificationState(status, notified_at, resolved_at)
    return states


async def prepare_alert_notification_ack(db: AsyncSession, claim: ClaimedNotification) -> None:
    ids = set((await db.scalars(select(Reference.alert_id).where(Reference.outbox_id == claim.id))).all())
    await lock_alert_notification_state(db, ids)


async def pending_active_notification_ids(db: AsyncSession, alert_ids: set[int]) -> set[int]:
    """Read unresolved delivery ownership in bounded batches, including dead jobs.

    A dead ACTIVE still owns delivery until explicit reconciliation. Selection
    must not create a replacement job that silently bypasses its failed stream.
    """
    ordered = sorted(alert_ids)
    pending: set[int] = set()
    for offset in range(0, len(ordered), 500):
        pending.update(
            (
                await db.scalars(
                    select(Reference.alert_id)
                    .join(Job, Job.id == Reference.outbox_id)
                    .where(
                        Reference.alert_id.in_(ordered[offset : offset + 500]),
                        Reference.action.in_(_ACTIVE_ACTIONS),
                        Job.channel == "telegram",
                        Job.status != "sent",
                    )
                    .distinct()
                )
            ).all()
        )
    return pending


@dataclass(frozen=True, order=True)
class AlertNotificationReference:
    alert_id: int
    action: NotificationAction

    def __post_init__(self) -> None:
        if self.alert_id <= 0 or self.action not in _ACTIVE_ACTIONS | {"created", "resolved"}:
            raise ValueError("Invalid alert notification reference")


async def enqueue_alert_notification(
    db: AsyncSession,
    draft: NotificationDraft,
    references: tuple[AlertNotificationReference, ...],
    *,
    now: datetime,
) -> int:
    """Flush domain references and enqueue in the caller's transaction; never commit."""
    if draft.channel != "telegram":
        raise ValueError("Alert delivery acknowledgement currently supports Telegram only")
    ordered = sorted(set(references))
    if not 1 <= len(ordered) <= 250:
        raise ValueError("An alert notification requires 1..250 unique references")
    # Domain rows created earlier in this transaction must exist before validation.
    await db.flush()
    ids = {reference.alert_id for reference in ordered}
    present = set((await db.scalars(select(Alert.id).where(Alert.id.in_(ids)))).all())
    if present != ids:
        raise ValueError("Cannot enqueue references to missing alerts")
    job_id = await NotificationOutboxRepository(db).enqueue(draft, now=now)
    stored = list((await db.scalars(select(Reference).where(Reference.outbox_id == job_id).with_for_update())).all())
    expected = {(item.alert_id, item.action) for item in ordered}
    if stored:
        if {(item.alert_id, item.action) for item in stored} != expected:
            raise ValueError("Idempotency key already belongs to different alert references")
    else:
        db.add_all(Reference(outbox_id=job_id, alert_id=item.alert_id, action=item.action) for item in ordered)
        await db.flush()
    return job_id


async def acknowledge_alert_notification(
    db: AsyncSession,
    claim: ClaimedNotification,
    delivered_at: datetime,
) -> None:
    """Called only after an accepted delivery ack, inside that same transaction."""
    if claim.channel != "telegram":
        raise ValueError("Unexpected alert notification channel")
    references = list(
        (
            await db.scalars(
                select(Reference).where(Reference.outbox_id == claim.id).order_by(Reference.alert_id, Reference.action)
            )
        ).all()
    )
    if not references:
        raise RuntimeError("Alert notification job has no domain references")
    ids = {reference.alert_id for reference in references}
    alerts = {
        alert.id: alert
        for alert in (
            await db.scalars(
                select(Alert)
                .where(Alert.id.in_(ids))
                .order_by(Alert.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    }
    incidents = IncidentRepository(db)
    for reference in references:
        alert = alerts.get(reference.alert_id)
        if alert is None:
            # Retention may already have removed this record. Never recreate it.
            continue
        if reference.action in _ACTIVE_ACTIONS:
            previous = alert.telegram_notified_at
            if previous is None or delivered_at > previous:
                alert.telegram_notified_at = delivered_at
        await incidents.add_notification_timeline_event_for_alert(
            alert=alert,
            action=reference.action,
            channel=claim.channel,
            notified_at=delivered_at,
            commit=False,
        )
    await db.flush()


async def deliver_alert_notification(
    sessions: async_sessionmaker[AsyncSession],
    sender: NotificationSender,
    *,
    policy: DeliveryPolicy = DeliveryPolicy(),
    clock: Callable[[], datetime] = utcnow,
    routed_sender: RoutedNotificationSender | None = None,
) -> str:
    """Bind transport acknowledgement to domain state for the alert worker."""
    return await deliver_one(
        sessions,
        sender,
        channel="telegram",
        policy=policy,
        clock=clock,
        on_delivered=acknowledge_alert_notification,
        routed_sender=routed_sender,
        before_acknowledge=prepare_alert_notification_ack,
    )
