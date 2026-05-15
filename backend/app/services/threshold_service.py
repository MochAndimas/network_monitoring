"""Service-layer workflows for threshold service."""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..repositories.threshold_repository import ThresholdRepository


DEFAULT_THRESHOLDS = {
    "ping_latency_warning": (100.0, "Ping latency warning threshold in milliseconds"),
    "ping_latency_critical": (200.0, "Ping latency critical threshold in milliseconds"),
    "cpu_warning": (settings.thresholds.cpu_warning, "CPU usage warning threshold in percent"),
    "ram_warning": (settings.thresholds.ram_warning, "Memory usage warning threshold in percent"),
    "disk_warning": (settings.thresholds.disk_warning, "Disk usage warning threshold in percent"),
    "packet_loss_warning": (20.0, "Packet loss threshold in percent"),
    "packet_loss_critical": (50.0, "Critical packet loss threshold in percent"),
    "jitter_warning": (30.0, "Jitter warning threshold in milliseconds"),
    "jitter_critical": (75.0, "Critical jitter threshold in milliseconds"),
    "switch_ping_latency_warning": (50.0, "Switch ping latency warning threshold in milliseconds"),
    "switch_ping_latency_critical": (100.0, "Switch ping latency critical threshold in milliseconds"),
    "switch_packet_loss_warning": (5.0, "Switch packet loss warning threshold in percent"),
    "switch_packet_loss_critical": (50.0, "Switch critical packet loss threshold in percent"),
    "switch_jitter_warning": (20.0, "Switch jitter warning threshold in milliseconds"),
    "switch_jitter_critical": (50.0, "Switch critical jitter threshold in milliseconds"),
    "nas_ping_latency_warning": (50.0, "NAS ping latency warning threshold in milliseconds"),
    "nas_ping_latency_critical": (150.0, "NAS ping latency critical threshold in milliseconds"),
    "nas_packet_loss_warning": (2.0, "NAS packet loss warning threshold in percent"),
    "nas_packet_loss_critical": (20.0, "NAS critical packet loss threshold in percent"),
    "nas_jitter_warning": (20.0, "NAS jitter warning threshold in milliseconds"),
    "nas_jitter_critical": (50.0, "NAS critical jitter threshold in milliseconds"),
    "nas_system_temperature_warning": (65.0, "NAS system temperature warning threshold in Celsius"),
    "nas_system_temperature_critical": (75.0, "NAS system temperature critical threshold in Celsius"),
    "nas_disk_temperature_warning": (45.0, "NAS disk temperature warning threshold in Celsius"),
    "nas_disk_temperature_critical": (55.0, "NAS disk temperature critical threshold in Celsius"),
    "printer_ping_latency_warning": (250.0, "Printer ping latency warning threshold in milliseconds"),
    "printer_ping_latency_critical": (800.0, "Printer ping latency critical threshold in milliseconds"),
    "printer_jitter_warning": (50.0, "Printer jitter warning threshold in milliseconds"),
    "printer_jitter_critical": (150.0, "Printer critical jitter threshold in milliseconds"),
    "voip_ping_latency_warning": (200.0, "VoIP ping latency warning threshold in milliseconds"),
    "voip_ping_latency_critical": (500.0, "VoIP ping latency critical threshold in milliseconds"),
    "dns_resolution_warning": (500.0, "DNS resolution warning threshold in milliseconds"),
    "http_response_warning": (1000.0, "HTTP response warning threshold in milliseconds"),
    "mikrotik_connected_clients_warning": (170.0, "Mikrotik connected clients warning threshold"),
    "mikrotik_interface_mbps_warning": (250.0, "Mikrotik interface traffic warning threshold in Mbps"),
    "mikrotik_firewall_spike_pps_warning": (1000.0, "Mikrotik firewall rule packet-rate spike threshold in packets per second"),
    "mikrotik_firewall_spike_mbps_warning": (50.0, "Mikrotik firewall rule traffic spike threshold in Mbps"),
    "printer_ink_warning": (20.0, "Printer ink warning threshold in percent"),
    "printer_ink_critical": (10.0, "Printer ink critical threshold in percent"),
}


async def ensure_default_thresholds(db: AsyncSession, *, commit: bool = True) -> list:
    """Ensure default thresholds in the service layer."""
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
        if commit:
            await db.commit()
        else:
            await db.flush()

    return sorted(thresholds, key=lambda threshold: threshold.key)


async def list_threshold_rows(db: AsyncSession) -> list[dict]:
    """List threshold rows in the service layer."""
    await ensure_default_thresholds(db, commit=True)
    return [
        {"id": threshold.id, "key": threshold.key, "value": threshold.value, "description": threshold.description}
        for threshold in await ThresholdRepository(db).list_thresholds()
    ]


async def get_threshold_map(db: AsyncSession, *, commit: bool = True) -> dict[str, float]:
    """Return get threshold map used by threshold configuration."""
    await ensure_default_thresholds(db, commit=commit)
    return {threshold.key: threshold.value for threshold in await ThresholdRepository(db).list_thresholds()}


async def update_threshold_value(db: AsyncSession, key: str, value: float) -> dict:
    """Update threshold value in the service layer."""
    if key not in DEFAULT_THRESHOLDS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Threshold not found")
    _, description = DEFAULT_THRESHOLDS[key]
    threshold = await ThresholdRepository(db).upsert_threshold(key, value, description)
    return {"id": threshold.id, "key": threshold.key, "value": threshold.value, "description": threshold.description}
