from sqlalchemy.orm import Session

from ...repositories.device_repository import DeviceRepository
from ..helpers import build_ping_metric, build_ping_quality_metrics, collect_ping_samples, latest_successful_ping, safe_ping


DEVICE_TYPES = ["nvr", "switch", "access_point", "printer"]


def run_device_checks(db: Session) -> list[dict]:
    devices = DeviceRepository(db).list_by_types(DEVICE_TYPES, active_only=True)
    metrics: list[dict] = []

    for device in devices:
        if device.device_type == "access_point":
            samples = collect_ping_samples(device.ip_address)
            metrics.append(build_ping_metric(device.id, latest_successful_ping(samples)))
            metrics.extend(build_ping_quality_metrics(device.id, samples))
            continue

        metrics.append(build_ping_metric(device.id, safe_ping(device.ip_address)))

    return metrics
