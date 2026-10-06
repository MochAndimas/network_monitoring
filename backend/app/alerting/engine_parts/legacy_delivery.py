"""Legacy delivery: focused metric/alert workflow responsibilities."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from ...core.time import utcnow
from ...models.alert import Alert
from ...repositories.alert_repository import AlertRepository
from ...repositories.incident_repository import IncidentRepository
from ..notifiers.telegram_notifier import send_telegram_alert
from .dependencies import LegacySender
from .notification_formatting import _build_telegram_message as _build_telegram_message
from .notification_formatting import _group_telegram_events as _group_telegram_events
from .notification_formatting import _order_telegram_events as _order_telegram_events


async def _send_telegram_events(
    db,
    alert_repository: AlertRepository,
    events: list[dict],
    *,
    commit: bool,
    sender: LegacySender = send_telegram_alert,
    clock: Callable[[], datetime] = utcnow,
) -> None:
    """Send Telegram events and mark active alerts that were successfully delivered."""
    incident_repository = IncidentRepository(db)
    events = _order_telegram_events(await _refresh_telegram_events(db, events))
    grouped_events = _group_telegram_events(events)
    if not grouped_events:
        return

    grouped_items = list(grouped_events.values())
    results = await asyncio.gather(
        *(sender(_build_telegram_message(group)) for group in grouped_items),
        return_exceptions=True,
    )
    notified_at = clock()
    has_marked_alerts = False
    has_notification_events = False
    for group, result in zip(grouped_items, results, strict=True):
        # ``None`` remains accepted for legacy test notifiers; the real notifier
        # returns False when Telegram was skipped or rejected the request.
        if isinstance(result, Exception) or result is False:
            continue
        for event in group:
            event_alerts = event.get("alerts") or [event.get("alert")]
            for alert in event_alerts:
                if alert is None:
                    continue
                await incident_repository.add_notification_timeline_event_for_alert(
                    alert=alert,
                    action=str(event.get("action") or "active"),
                    channel="telegram",
                    notified_at=notified_at,
                    commit=False,
                )
                has_notification_events = True
                if str(event.get("action") or "active").lower() in {"active", "active_reminder", "summary_active"}:
                    await alert_repository.mark_telegram_notified(alert, notified_at, commit=False)
                    has_marked_alerts = True

    if has_marked_alerts or has_notification_events:
        if commit:
            await db.commit()
        else:
            await db.flush()


async def _refresh_telegram_events(db, events: list[dict]) -> list[dict]:
    """Re-read active events before sending so stale ACTIVE messages do not outlive resolved alerts."""
    refreshed_events: list[dict] = []
    for event in events:
        action = str(event.get("action") or "active").lower()
        if action not in {"active", "active_reminder", "summary_active"}:
            refreshed_events.append(event)
            continue

        alert_id = event.get("alert_id")
        if alert_id is None:
            refreshed_events.append(event)
            continue

        fresh_alert = await db.get(Alert, alert_id)
        if fresh_alert is None:
            continue
        if fresh_alert.telegram_notified_at is not None and action != "active_reminder":
            continue
        fresh_event = {**event, "alert": fresh_alert}
        if str(fresh_alert.status or "").lower() == "active":
            refreshed_events.append(fresh_event)
            continue
        if str(fresh_alert.status or "").lower() == "resolved":
            continue
    return refreshed_events
