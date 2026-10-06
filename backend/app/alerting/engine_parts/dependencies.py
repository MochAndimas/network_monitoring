"""Per-evaluation dependencies; tests never need to mutate engine module state."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...core.time import utcnow
from ...repositories.alert_repository import AlertRepository
from ...repositories.device_repository import DeviceRepository
from ...repositories.incident_repository import IncidentRepository
from ...repositories.metric_repository import MetricRepository
from .notification_policy import TelegramNotificationPolicy

LegacySender = Callable[[str], Awaitable[bool | None]]
ExpectedAlertLoader = Callable[..., Awaitable[dict[tuple[int | None, str], dict[str, Any]]]]


@dataclass(frozen=True)
class AlertEvaluationDependencies:
    clock: Callable[[], datetime] = utcnow
    alert_repository: Callable[[AsyncSession], AlertRepository] = AlertRepository
    incident_repository: Callable[[AsyncSession], IncidentRepository] = IncidentRepository
    metric_repository: Callable[[AsyncSession], MetricRepository] = MetricRepository
    device_repository: Callable[[AsyncSession], DeviceRepository] = DeviceRepository
    expected_alerts: ExpectedAlertLoader | None = None
    legacy_sender: LegacySender | None = None
    notification_policy: TelegramNotificationPolicy | None = None
