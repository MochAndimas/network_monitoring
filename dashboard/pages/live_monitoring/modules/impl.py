"""Compatibility facade for live monitoring dashboard helper modules."""

from urllib.parse import urlencode

import pandas as pd

from .constants import CHART_WINDOW_OPTIONS, INTERNET_ONLY_METRICS, PRINTER_METRIC_NAMES, STATUS_OPTIONS
from .data import (
    _default_device_option_label,
    _default_nas_trend_metrics,
    _fetch_device_history_rows,
    _fetch_history_pages,
    _fetch_history_rows_bulk,
    _fetch_latest_device_snapshot,
    _filter_history_rows,
    _filter_metric_names,
    _history_query_params,
    _is_nas_card_only_metric,
    _latest_snapshot_frame,
    _paginate_frame,
    _prepare_history_frame,
    _should_hide_metric_for_device,
    _snapshot_pagination_controls,
)
from .device import (
    _default_mikrotik_trend_metrics,
    _dynamic_mikrotik_metric_table,
    _firewall_view,
    _format_bytes,
    _format_mbps,
    _format_percent,
    _interface_view,
    _is_dynamic_mikrotik_metric,
    _latest_metric_display_from_map,
    _latest_metric_snapshot_map,
    _latest_metric_value_from_map,
    _nas_volume_capacity_view,
    _render_mikrotik_history_section,
    _render_nas_history_section,
    _render_printer_history_section,
)
from .formatting import _format_duration, _friendly_metric_name, _metric_filter_label
from .rendering import (
    _entity_volume_frame,
    _format_celsius,
    _format_metric_numeric,
    _health_score_percent,
    _metric_kpi_summary,
    _non_numeric_metric_timeline,
    _raw_history_view,
    _recent_anomaly_frame,
    _render_metric_trend_section,
    _render_stat_card,
    _status_counts_frame,
    _status_label_for_display,
    _trend_direction_text,
)
from shared.device_utils import is_mikrotik_device

try:
    from components.api import paged_items, paged_meta
    from components.time_utils import format_wib_timestamp, wib_date_boundary_to_utc_iso
    from components.ui import normalize_status_label
except ModuleNotFoundError:  # pragma: no cover - supports package imports outside Streamlit's app root
    from dashboard.components.api import paged_items, paged_meta
    from dashboard.components.time_utils import format_wib_timestamp, wib_date_boundary_to_utc_iso
    from dashboard.components.ui import normalize_status_label

__all__ = ['CHART_WINDOW_OPTIONS', 'INTERNET_ONLY_METRICS', 'PRINTER_METRIC_NAMES', 'STATUS_OPTIONS', '_default_device_option_label', '_default_nas_trend_metrics', '_fetch_device_history_rows', '_fetch_history_pages', '_fetch_history_rows_bulk', '_fetch_latest_device_snapshot', '_filter_history_rows', '_filter_metric_names', '_history_query_params', '_is_nas_card_only_metric', '_latest_snapshot_frame', '_paginate_frame', '_prepare_history_frame', '_should_hide_metric_for_device', '_snapshot_pagination_controls', '_default_mikrotik_trend_metrics', '_dynamic_mikrotik_metric_table', '_firewall_view', '_format_bytes', '_format_mbps', '_format_percent', '_interface_view', '_is_dynamic_mikrotik_metric', '_latest_metric_display_from_map', '_latest_metric_snapshot_map', '_latest_metric_value_from_map', '_nas_volume_capacity_view', '_render_mikrotik_history_section', '_render_nas_history_section', '_render_printer_history_section', '_format_duration', '_friendly_metric_name', '_metric_filter_label', '_entity_volume_frame', '_format_celsius', '_format_metric_numeric', '_health_score_percent', '_metric_kpi_summary', '_non_numeric_metric_timeline', '_raw_history_view', '_recent_anomaly_frame', '_render_metric_trend_section', '_render_stat_card', '_status_counts_frame', '_status_label_for_display', '_trend_direction_text', 'is_mikrotik_device', 'paged_items', 'paged_meta', 'format_wib_timestamp', 'wib_date_boundary_to_utc_iso', 'normalize_status_label', 'urlencode', 'pd']
