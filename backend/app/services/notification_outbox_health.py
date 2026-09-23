"""Fixed-cardinality queue health shared by JSON and Prometheus outputs."""

from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ..repositories.notification_outbox_health_repository import read_notification_queue


@dataclass(frozen=True)
class NotificationQueueHealth:
    pending: int = 0
    processing: int = 0
    dead: int = 0
    due_pending: int = 0
    expired_leases: int = 0
    oldest_pending_age_seconds: float = 0.0
    oldest_processing_age_seconds: float = 0.0
    oldest_dead_age_seconds: float = 0.0


async def build_notification_queue_health(db: AsyncSession, *, now: datetime) -> NotificationQueueHealth:
    rows = await read_notification_queue(db, channel="telegram", now=now)
    counts = {row.status: row.jobs for row in rows}
    ages = {
        row.status: max(0.0, (now - row.oldest_created_at).total_seconds())
        if row.oldest_created_at is not None
        else 0.0
        for row in rows
    }
    return NotificationQueueHealth(
        pending=counts.get("pending", 0),
        processing=counts.get("processing", 0),
        dead=counts.get("dead", 0),
        due_pending=sum(row.due_pending for row in rows),
        expired_leases=sum(row.expired_leases for row in rows),
        oldest_pending_age_seconds=ages.get("pending", 0.0),
        oldest_processing_age_seconds=ages.get("processing", 0.0),
        oldest_dead_age_seconds=ages.get("dead", 0.0),
    )


def render_notification_queue_metrics(health: NotificationQueueHealth) -> str:
    """Values are database snapshots; do not sum them across API replicas."""
    values = asdict(health)
    lines = [
        "# HELP network_monitoring_notification_outbox_jobs Unfinished Telegram jobs by status.",
        "# TYPE network_monitoring_notification_outbox_jobs gauge",
    ]
    for status in ("pending", "processing", "dead"):
        lines.append(
            f'network_monitoring_notification_outbox_jobs{{channel="telegram",status="{status}"}} {values[status]}'
        )
    lines.extend(
        [
            "# HELP network_monitoring_notification_outbox_oldest_age_seconds Age since creation, not lease age; zero when empty.",
            "# TYPE network_monitoring_notification_outbox_oldest_age_seconds gauge",
        ]
    )
    for status in ("pending", "processing", "dead"):
        age = values[f"oldest_{status}_age_seconds"]
        lines.append(
            f'network_monitoring_notification_outbox_oldest_age_seconds{{channel="telegram",status="{status}"}} {age}'
        )
    for field, help_text in (
        ("due_pending", "Pending jobs due by time; includes FIFO-blocked jobs."),
        ("expired_leases", "Processing jobs whose lease has expired."),
    ):
        name = f"network_monitoring_notification_outbox_{field}"
        lines.extend(
            [f"# HELP {name} {help_text}", f"# TYPE {name} gauge", f'{name}{{channel="telegram"}} {values[field]}']
        )
    return "\n".join(lines) + "\n"
