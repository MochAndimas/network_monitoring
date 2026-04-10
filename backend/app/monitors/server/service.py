import psutil
from sqlalchemy.orm import Session

from ...repositories.device_repository import DeviceRepository
from ...services.monitoring_service import utcnow
from ..helpers import build_ping_metric, safe_ping


def run_server_checks(db: Session) -> list[dict]:
    servers = DeviceRepository(db).list_by_type("server", active_only=True)
    metrics: list[dict] = []

    for index, server in enumerate(servers):
        checked_at = utcnow()
        metrics.append(build_ping_metric(server.id, safe_ping(server.ip_address)))

        # Local host metrics are only attached to the first active server entry.
        if index > 0:
            continue

        metrics.extend(
            [
                {
                    "device_id": server.id,
                    "metric_name": "cpu_percent",
                    "metric_value": f"{psutil.cpu_percent(interval=0.1):.2f}",
                    "status": "ok",
                    "unit": "%",
                    "checked_at": checked_at,
                },
                {
                    "device_id": server.id,
                    "metric_name": "memory_percent",
                    "metric_value": f"{psutil.virtual_memory().percent:.2f}",
                    "status": "ok",
                    "unit": "%",
                    "checked_at": checked_at,
                },
                {
                    "device_id": server.id,
                    "metric_name": "disk_percent",
                    "metric_value": f"{psutil.disk_usage('/').percent:.2f}",
                    "status": "ok",
                    "unit": "%",
                    "checked_at": checked_at,
                },
                {
                    "device_id": server.id,
                    "metric_name": "boot_time_epoch",
                    "metric_value": f"{int(psutil.boot_time())}",
                    "status": "ok",
                    "unit": "epoch",
                    "checked_at": checked_at,
                },
            ]
        )

    return metrics
