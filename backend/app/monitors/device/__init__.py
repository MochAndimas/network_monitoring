"""Package marker and public imports for backend.app.monitors.device."""
"""Device monitoring collectors and their adapters."""

from .adapters import DeviceCollectorAdapter, collector_for_device_type

__all__ = ["DeviceCollectorAdapter", "collector_for_device_type"]
