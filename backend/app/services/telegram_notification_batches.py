"""Bound Telegram message groups without splitting one domain event's ack."""

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
    """Greedily pack a homogeneous, ordered group into independently acked jobs.

    Each event remains atomic: splitting one event over multiple jobs would let
    the first delivery incorrectly acknowledge the entire domain event. Reject
    an oversized individual event until multipart acknowledgement is available.
    The caller supplies deterministic order and a single site/action/severity.
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
            if len(candidate_refs) > max_references:
                raise ValueError("Individual Telegram event exceeds reference limit")
            if len(rendered.encode("utf-16-le")) // 2 > max_message_units:
                raise ValueError("Individual Telegram event exceeds message limit")
        current, refs, message = candidate, candidate_refs, rendered
    if current:
        batches.append(TelegramMessageBatch(message, tuple(sorted(refs))))
    return batches
