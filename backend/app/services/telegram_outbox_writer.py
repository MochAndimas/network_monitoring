"""Persist grouped Telegram events with stable identities and explicit routing.

The adapter performs no network I/O and never commits its caller's session.
"""

from dataclasses import dataclass
import hashlib
import json
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..alerting.engine_parts.notification_formatting import (
    _group_telegram_events,
    _filter_recent_telegram_events,
)
from ..core.time import utcnow
from ..models.notification_outbox import NotificationOutbox as Job
from ..models.notification_outbox_alert import NotificationOutboxAlert as Reference
from ..repositories.notification_outbox_repository import NotificationDraft, NotificationOutboxRepository
from .alert_notification_outbox_service import (
    enqueue_alert_notification,
    lock_alert_notification_state,
)

from .notification_routing import previous_active_route
from .telegram_notification_batches import event_references, split_telegram_events

_ACTION_RANK = {"active": 0, "active_reminder": 1, "summary_active": 2, "created": 2, "resolved": 3}


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class TelegramOutboxWriter:
    destination: str

    def __post_init__(self) -> None:
        # Numeric IDs are stable; mutable @usernames must be resolved by the
        # caller before snapshotting. Tokens are never stored in an outbox row.
        if not re.fullmatch(r"-?[0-9]{1,20}", self.destination):
            raise ValueError("Telegram outbox requires a numeric chat ID")

    async def __call__(self, db: AsyncSession, events: list[dict]) -> None:
        if not events:
            return
        # Capture the generation used by selection before any ORM refresh.
        expected_reminders = {}
        for event in events:
            if event.get("action") == "active_reminder":
                for alert in event.get("alerts") or [event.get("alert")]:
                    if alert is not None:
                        expected_reminders[alert.id] = alert.telegram_notified_at
        await db.flush()
        current = await lock_alert_notification_state(
            db, {ref.alert_id for event in events for ref in event_references(event)}
        )
        groups = _group_telegram_events(_filter_recent_telegram_events(events))
        routed_groups: dict[tuple[tuple[str, str, str], str, str], list[dict]] = {}
        for key, group in groups.items():
            for event in group:
                destination = self.destination
                stream = "telegram:v1:" + _hash([destination, key[0]])
                if key[1] == "resolved":
                    # Match the actual persisted ACTIVE route, including sent jobs.
                    # Never reroute a resolution from a pending/dead predecessor.
                    previous = await previous_active_route(db, event_references(event)[0].alert_id)
                    if previous is not None:
                        if previous[0] is None:
                            raise ValueError("Reconcile legacy ACTIVE destination before resolution")
                        destination, stream = previous[0], previous[1]
                routed_groups.setdefault((key, destination, stream), []).append(event)
        repository = NotificationOutboxRepository(db)
        await repository.lock_streams([("telegram", stream) for _, _, stream in routed_groups])
        for key, destination, stream in sorted(
            routed_groups, key=lambda item: (_ACTION_RANK.get(item[0][1], 99), item)
        ):
            group = routed_groups[(key, destination, stream)]
            group_ids = sorted({ref.alert_id for event in group for ref in event_references(event)})
            pending_ids: set[int] = set()
            for offset in range(0, len(group_ids), 500):
                pending_ids.update(
                    (
                        await db.scalars(
                            select(Reference.alert_id)
                            .join(Job, Job.id == Reference.outbox_id)
                            .where(
                                Reference.alert_id.in_(group_ids[offset : offset + 500]),
                                Reference.action.in_(["active", "active_reminder", "summary_active"]),
                                Job.channel == "telegram",
                                Job.status != "sent",
                            )
                            .with_for_update()
                        )
                    ).all()
                )
            selected = []
            for event in sorted(group, key=lambda item: (str(item.get("alert_id")), str(item.get("alert_type")))):
                refs = event_references(event)
                # A locking read sees jobs committed while waiting for the stream.
                if key[1] != "resolved" and any(ref.alert_id in pending_ids for ref in refs):
                    continue
                if any(ref.alert_id not in current for ref in refs):
                    raise ValueError("Cannot snapshot missing alerts")
                if key[1] in {"active", "summary_active", "active_reminder"}:
                    if any(current[ref.alert_id].status != "active" for ref in refs):
                        continue
                    if key[1] != "active_reminder":
                        if any(current[ref.alert_id].notified_at is not None for ref in refs):
                            continue
                    elif any(
                        ref.alert_id not in expected_reminders
                        or current[ref.alert_id].notified_at is None
                        or current[ref.alert_id].notified_at != expected_reminders[ref.alert_id]
                        for ref in refs
                    ):
                        # Acknowledgement changed the selected reminder generation.
                        # Let the next evaluation recompute its cooldown.
                        continue
                selected.append(event)
            if not selected:
                continue
            for batch in split_telegram_events(selected):
                refs = batch.references
                identities = []
                for ref in refs:
                    state = current[ref.alert_id]
                    generation = state.resolved_at if ref.action == "resolved" else state.notified_at
                    identities.append([ref.alert_id, ref.action, generation.isoformat() if generation else None])
                draft = NotificationDraft(
                    _hash(["telegram:v1", destination, key, identities]),
                    stream,
                    "telegram",
                    batch.message,
                    destination,
                )
                await enqueue_alert_notification(db, draft, refs, now=utcnow())
