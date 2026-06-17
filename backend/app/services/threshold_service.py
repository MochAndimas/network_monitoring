"""Service-layer workflows for threshold and alert intelligence controls."""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..models.device import Device
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


async def get_threshold_runtime_config(db: AsyncSession, *, commit: bool = True) -> dict:
    """Return global thresholds plus active override rows for alert evaluation."""
    thresholds = await get_threshold_map(db, commit=commit)
    overrides = await ThresholdRepository(db).list_threshold_overrides(active_only=True)
    return {
        "thresholds": thresholds,
        "overrides": [_threshold_override_payload(override) for override in overrides],
    }


async def update_threshold_value(db: AsyncSession, key: str, value: float) -> dict:
    """Update threshold value in the service layer."""
    if key not in DEFAULT_THRESHOLDS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Threshold not found")
    _, description = DEFAULT_THRESHOLDS[key]
    threshold = await ThresholdRepository(db).upsert_threshold(key, value, description)
    return {"id": threshold.id, "key": threshold.key, "value": threshold.value, "description": threshold.description}


async def list_threshold_override_rows(db: AsyncSession) -> list[dict]:
    """List scoped threshold overrides."""
    return [_threshold_override_payload(row) for row in await ThresholdRepository(db).list_threshold_overrides()]


async def create_threshold_override(db: AsyncSession, payload: dict) -> dict:
    """Create a scoped threshold override after validation."""
    threshold_key = str(payload.get("threshold_key") or "").strip()
    if threshold_key not in DEFAULT_THRESHOLDS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Threshold not found")
    scope_values = [
        payload.get("device_id"),
        str(payload.get("device_type") or "").strip() or None,
        str(payload.get("site") or "").strip() or None,
    ]
    if sum(value is not None for value in scope_values) != 1:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Exactly one override scope is required")
    row = await ThresholdRepository(db).create_threshold_override(
        {
            "threshold_key": threshold_key,
            "value": float(payload["value"]),
            "device_id": payload.get("device_id"),
            "device_type": str(payload.get("device_type") or "").strip() or None,
            "site": str(payload.get("site") or "").strip() or None,
            "description": str(payload.get("description") or "").strip() or None,
            "is_active": True,
        }
    )
    return _threshold_override_payload(row)


async def deactivate_threshold_override(db: AsyncSession, override_id: int) -> bool:
    """Deactivate a scoped threshold override."""
    return await ThresholdRepository(db).deactivate_threshold_override(override_id)


async def list_maintenance_window_rows(db: AsyncSession) -> list[dict]:
    """List maintenance windows."""
    return [_maintenance_window_payload(row) for row in await ThresholdRepository(db).list_maintenance_windows()]


async def create_maintenance_window(db: AsyncSession, payload: dict, *, actor: str | None = None) -> dict:
    """Create a maintenance window after scope and date validation."""
    starts_at = payload["starts_at"]
    ends_at = payload["ends_at"]
    if ends_at <= starts_at:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ends_at must be after starts_at")
    device_id = payload.get("device_id")
    site = str(payload.get("site") or "").strip() or None
    if (device_id is None and site is None) or (device_id is not None and site is not None):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Exactly one maintenance scope is required")
    row = await ThresholdRepository(db).create_maintenance_window(
        {
            "name": str(payload.get("name") or "").strip() or "Maintenance",
            "device_id": device_id,
            "site": site,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "reason": str(payload.get("reason") or "").strip() or None,
            "is_active": True,
            "created_by": actor,
        }
    )
    return _maintenance_window_payload(row)


async def deactivate_maintenance_window(db: AsyncSession, window_id: int) -> bool:
    """Deactivate a maintenance window."""
    return await ThresholdRepository(db).deactivate_maintenance_window(window_id)


def threshold_for_device(
    thresholds: dict[str, float],
    overrides: list[dict],
    device: Device,
    key: str,
) -> float:
    """Resolve scoped threshold with device > device_type > site > type-global > global fallback."""
    candidates = [
        f"{device.device_type}_{key}" if device.device_type else key,
        key,
    ]
    for threshold_key in candidates:
        for scope_name, scope_value in (
            ("device_id", device.id),
            ("device_type", device.device_type),
            ("site", device.site),
        ):
            for override in overrides:
                if override.get("threshold_key") != threshold_key:
                    continue
                if override.get(scope_name) is not None and str(override.get(scope_name)) == str(scope_value):
                    return float(override["value"])
        if threshold_key in thresholds:
            return thresholds[threshold_key]
    return thresholds[key]


def _threshold_override_payload(row) -> dict:
    return {
        "id": row.id,
        "threshold_key": row.threshold_key,
        "value": row.value,
        "device_id": row.device_id,
        "device_type": row.device_type,
        "site": row.site,
        "description": row.description,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _maintenance_window_payload(row) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "device_id": row.device_id,
        "site": row.site,
        "starts_at": row.starts_at,
        "ends_at": row.ends_at,
        "reason": row.reason,
        "is_active": row.is_active,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
