"""Resolve lifecycle routing from immutable outbox history."""

from datetime import timedelta
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from ..core.config import settings
from ..core.time import utcnow
from ..models.alert import Alert
from ..models.notification_outbox import NotificationOutbox as Job
from ..models.notification_outbox_alert import NotificationOutboxAlert as Reference


async def previous_active_route(db: AsyncSession, alert_id: int) -> tuple[str | None, str] | None:
    base = (
        select(Job.destination, Job.stream_key)
        .join(Reference, Reference.outbox_id == Job.id)
        .where(
            Reference.action.in_(["active", "active_reminder", "summary_active"]),
            Job.channel == "telegram",
        )
    )
    own = (await db.execute(base.where(Reference.alert_id == alert_id).order_by(Job.id.desc()).limit(1))).first()
    if own is not None:
        return own.destination, own.stream_key
    alert = await db.get(Alert, alert_id)
    if alert is None or alert.device_id is None:
        return None
    # A short-lived replacement can resolve an already announced logical issue.
    # Bound this fallback; an unrelated old incident must not own today's route.
    since = (alert.resolved_at or utcnow()) - timedelta(
        seconds=max(settings.telegram.resolved_correlation_window_seconds, 0)
    )
    sibling = (
        await db.execute(
            base.join(Alert, Alert.id == Reference.alert_id)
            .where(
                Alert.device_id == alert.device_id,
                Alert.alert_type == alert.alert_type,
                or_(Job.created_at >= since, Job.delivered_at >= since),
            )
            .order_by(Job.id.desc())
            .limit(1)
        )
    ).first()
    return (sibling.destination, sibling.stream_key) if sibling is not None else None
