"""Device-related formatting and classification helpers."""

from __future__ import annotations


def format_device_label(device: dict) -> str:
    """Render a consistent `<name> (<type>)` label for a device record."""
    return f'{device["name"]} ({device["device_type"]})'


def is_mikrotik_device(device_type: str | None, device_name: str | None) -> bool:
    """Return True when a device should be treated as a Mikrotik device."""
    normalized_type = str(device_type or "").lower()
    normalized_name = str(device_name or "").lower()
    return normalized_type == "mikrotik" or "mikrotik" in normalized_name

