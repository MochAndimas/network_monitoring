"""Define module logic for `shared/device_utils.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations


def format_device_label(device: dict) -> str:
    """Render a stable ``<name> (<type>)`` label from a device payload.

    Args:
        device: Mapping that includes ``name`` and ``device_type`` keys.

    Returns:
        Human-readable label used in dashboards and selector controls.
    """
    return f'{device["name"]} ({device["device_type"]})'


def is_mikrotik_device(device_type: str | None, device_name: str | None) -> bool:
    """Determine whether a device should be handled as a Mikrotik target.

    The check accepts either an explicit type match or a name containing
    ``mikrotik`` (case-insensitive) to support partially-normalized records.

    Args:
        device_type: Stored device type value, if available.
        device_name: Device name/label, if available.

    Returns:
        ``True`` when the device should be processed by Mikrotik-specific logic.
    """
    normalized_type = str(device_type or "").lower()
    normalized_name = str(device_name or "").lower()
    return normalized_type == "mikrotik" or "mikrotik" in normalized_name

