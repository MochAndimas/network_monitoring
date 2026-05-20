"""Device-specific live monitoring compatibility facade."""

from .device_common import (
    _format_bytes,
    _format_mbps,
    _format_percent,
    _latest_metric_display_from_map,
    _latest_metric_snapshot_map,
    _latest_metric_value_from_map,
    _nas_volume_capacity_view,
)
from .mikrotik import (
    _default_mikrotik_trend_metrics,
    _dynamic_mikrotik_metric_table,
    _firewall_view,
    _interface_view,
    _is_dynamic_mikrotik_metric,
    _render_mikrotik_history_section,
)
from .nas import _render_nas_history_section
from .printer import _render_printer_history_section

__all__ = [
    "_latest_metric_snapshot_map",
    "_latest_metric_value_from_map",
    "_latest_metric_display_from_map",
    "_nas_volume_capacity_view",
    "_format_percent",
    "_format_bytes",
    "_format_mbps",
    "_dynamic_mikrotik_metric_table",
    "_interface_view",
    "_firewall_view",
    "_render_mikrotik_history_section",
    "_render_nas_history_section",
    "_is_dynamic_mikrotik_metric",
    "_default_mikrotik_trend_metrics",
    "_render_printer_history_section",
]
