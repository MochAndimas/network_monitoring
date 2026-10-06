"""Pack events into jobs; oversized events retain one atomic domain acknowledgement."""

from dataclasses import dataclass
from typing import cast

from ..alerting.engine_parts.notification_formatting import _build_telegram_message
from .alert_notification_outbox_service import AlertNotificationReference, NotificationAction


@dataclass(frozen=True)
class TelegramMessageBatch:
    message: str
    references: tuple[AlertNotificationReference, ...]


def event_references(event: dict) -> tuple[AlertNotificationReference, ...]:
    action = cast(NotificationAction, str(event.get("action") or "active").lower())
    ids = {alert.id for alert in event.get("alerts") or []}
    if not ids:
        ids = {event.get("alert_id")}
    references = []
    for alert_id in ids:
        if not isinstance(alert_id, int) or isinstance(alert_id, bool):
            raise ValueError("Notification events require persisted integer alert IDs")
        references.append(AlertNotificationReference(alert_id, action))
    return tuple(sorted(references))


def split_telegram_events(
    events: list[dict], *, max_message_units: int = 4096, max_references: int = 250
) -> list[TelegramMessageBatch]:
    """Pack normal events; the delivery cursor handles oversized atomic events.

    Message/reference limits bound normal batches, not individual domain events.
    One oversized event stays in one job so no partial send acknowledges it.
    """
    if not 0 < max_message_units <= 4096 or not 0 < max_references <= 250:
        raise ValueError("Invalid Telegram batching limits")
    batches: list[TelegramMessageBatch] = []
    current: list[dict] = []
    refs: set[AlertNotificationReference] = set()
    message = ""
    seen: set[AlertNotificationReference] = set()
    for event in events:
        event_refs = set(event_references(event))
        if seen & event_refs:
            raise ValueError("Overlapping alert references in Telegram group")
        seen.update(event_refs)
        candidate = current + [event]
        candidate_refs = refs | event_refs
        rendered = _build_telegram_message(candidate)
        fits = len(candidate_refs) <= max_references and len(rendered.encode("utf-16-le")) // 2 <= max_message_units
        if not fits:
            if current:
                batches.append(TelegramMessageBatch(message, tuple(sorted(refs))))
            candidate = [event]
            candidate_refs = event_refs
            rendered = _build_telegram_message(candidate)
        current, refs, message = candidate, candidate_refs, rendered
    if current:
        batches.append(TelegramMessageBatch(message, tuple(sorted(refs))))
    return batches
