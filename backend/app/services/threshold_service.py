from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..repositories.threshold_repository import ThresholdRepository


DEFAULT_THRESHOLDS = {
    "ping_latency_warning": (100.0, "Ping latency warning threshold in milliseconds"),
    "ping_latency_critical": (200.0, "Ping latency critical threshold in milliseconds"),
    "cpu_warning": (settings.cpu_warning_threshold, "CPU usage warning threshold in percent"),
    "ram_warning": (settings.ram_warning_threshold, "Memory usage warning threshold in percent"),
    "disk_warning": (settings.disk_warning_threshold, "Disk usage warning threshold in percent"),
    "packet_loss_warning": (20.0, "Packet loss threshold in percent"),
    "packet_loss_critical": (50.0, "Critical packet loss threshold in percent"),
    "jitter_warning": (30.0, "Jitter warning threshold in milliseconds"),
    "jitter_critical": (75.0, "Critical jitter threshold in milliseconds"),
    "dns_resolution_warning": (500.0, "DNS resolution warning threshold in milliseconds"),
    "http_response_warning": (1000.0, "HTTP response warning threshold in milliseconds"),
    "mikrotik_connected_clients_warning": (100.0, "Mikrotik connected clients warning threshold"),
    "mikrotik_interface_mbps_warning": (80.0, "Mikrotik interface traffic warning threshold in Mbps"),
    "mikrotik_firewall_spike_pps_warning": (1000.0, "Mikrotik firewall rule packet-rate spike threshold in packets per second"),
    "mikrotik_firewall_spike_mbps_warning": (50.0, "Mikrotik firewall rule traffic spike threshold in Mbps"),
    "printer_ink_warning": (20.0, "Printer ink warning threshold in percent"),
    "printer_ink_critical": (10.0, "Printer ink critical threshold in percent"),
}


async def ensure_default_thresholds(db: AsyncSession) -> list:
    repository = ThresholdRepository(db)
    existing_thresholds = {threshold.key: threshold for threshold in await repository.list_thresholds()}
    thresholds = list(existing_thresholds.values())
    created_any = False

    for key, (value, description) in DEFAULT_THRESHOLDS.items():
        existing = existing_thresholds.get(key)
        if existing is not None:
            continue
        threshold = await repository.upsert_threshold(key, value, description, commit=False)
        existing_thresholds[key] = threshold
        thresholds.append(threshold)
        created_any = True

    if created_any:
        await db.commit()

    return sorted(thresholds, key=lambda threshold: threshold.key)


async def list_threshold_rows(db: AsyncSession) -> list[dict]:
    await ensure_default_thresholds(db)
    return [
        {"id": threshold.id, "key": threshold.key, "value": threshold.value, "description": threshold.description}
        for threshold in await ThresholdRepository(db).list_thresholds()
    ]


async def get_threshold_map(db: AsyncSession) -> dict[str, float]:
    await ensure_default_thresholds(db)
    return {threshold.key: threshold.value for threshold in await ThresholdRepository(db).list_thresholds()}


async def update_threshold_value(db: AsyncSession, key: str, value: float) -> dict:
    if key not in DEFAULT_THRESHOLDS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Threshold not found")
    _, description = DEFAULT_THRESHOLDS[key]
    threshold = await ThresholdRepository(db).upsert_threshold(key, value, description)
    return {"id": threshold.id, "key": threshold.key, "value": threshold.value, "description": threshold.description}
