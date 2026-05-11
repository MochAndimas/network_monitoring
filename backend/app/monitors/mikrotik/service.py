"""Compatibility facade for Mikrotik monitoring collectors.

The implementation is split under ``backend.app.monitors.mikrotik.parts``.
This module keeps the historical import path stable for scheduler jobs and tests,
including module-level monkeypatch points such as ``connect``.
"""

from .parts import impl as _impl

FIREWALL_SPIKE_MBPS_WARNING = _impl.FIREWALL_SPIKE_MBPS_WARNING
FIREWALL_SPIKE_PPS_WARNING = _impl.FIREWALL_SPIKE_PPS_WARNING
MAX_DYNAMIC_METRIC_NAME_LENGTH = _impl.MAX_DYNAMIC_METRIC_NAME_LENGTH
settings = _impl.settings
connect = _impl.connect


def _sync_patchable_globals() -> None:
    """Forward facade-level monkeypatches into the implementation module."""
    _impl.connect = connect


async def run_mikrotik_checks(db) -> list[dict]:
    """Run Mikrotik checks while preserving historical monkeypatch behavior."""
    _sync_patchable_globals()
    return await _impl.run_mikrotik_checks(db)


_active_dhcp_lease_count = _impl._active_dhcp_lease_count
_bits_to_mbps = _impl._bits_to_mbps
_build_ping_metrics = _impl._build_ping_metrics
_connected_client_count = _impl._connected_client_count
_counter_per_second = _impl._counter_per_second
_counter_rate = _impl._counter_rate
_disk_used_bytes = _impl._disk_used_bytes
_dynamic_metric_name = _impl._dynamic_metric_name
_firewall_metrics = _impl._firewall_metrics
_firewall_rule_name = _impl._firewall_rule_name
_interface_metrics = _impl._interface_metrics
_is_active_dhcp_lease = _impl._is_active_dhcp_lease
_is_allowed_dynamic_name = _impl._is_allowed_dynamic_name
_latest_metric_map = _impl._latest_metric_map
_limit_items = _impl._limit_items
_list_mikrotik_devices = _impl._list_mikrotik_devices
_memory_used_bytes = _impl._memory_used_bytes
_metric = _impl._metric
_mikrotik_disk_percent = _impl._mikrotik_disk_percent
_mikrotik_memory_percent = _impl._mikrotik_memory_percent
_object_name = _impl._object_name
_queue_metrics = _impl._queue_metrics
_resolve_api_target_device = _impl._resolve_api_target_device
_safe_int = _impl._safe_int
_should_collect_ping = _impl._should_collect_ping
_slugify = _impl._slugify
_split_counter_pair = _impl._split_counter_pair
_truthy = _impl._truthy

__all__ = [
    "FIREWALL_SPIKE_MBPS_WARNING",
    "FIREWALL_SPIKE_PPS_WARNING",
    "MAX_DYNAMIC_METRIC_NAME_LENGTH",
    "connect",
    "run_mikrotik_checks",
    "settings",
    "_active_dhcp_lease_count",
    "_bits_to_mbps",
    "_build_ping_metrics",
    "_connected_client_count",
    "_counter_per_second",
    "_counter_rate",
    "_disk_used_bytes",
    "_dynamic_metric_name",
    "_firewall_metrics",
    "_firewall_rule_name",
    "_interface_metrics",
    "_is_active_dhcp_lease",
    "_is_allowed_dynamic_name",
    "_latest_metric_map",
    "_limit_items",
    "_list_mikrotik_devices",
    "_memory_used_bytes",
    "_metric",
    "_mikrotik_disk_percent",
    "_mikrotik_memory_percent",
    "_object_name",
    "_queue_metrics",
    "_resolve_api_target_device",
    "_safe_int",
    "_should_collect_ping",
    "_slugify",
    "_split_counter_pair",
    "_truthy",
]
