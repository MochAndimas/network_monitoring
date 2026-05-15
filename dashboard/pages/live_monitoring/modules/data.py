"""Live monitoring data loading and shaping helpers."""

from urllib.parse import urlencode

import pandas as pd
import streamlit as st

from shared.device_utils import format_device_label, is_mikrotik_device
from .constants import (
    INTERNET_ONLY_METRICS,
    NAS_CARD_ONLY_DYNAMIC_PREFIXES,
    NAS_CARD_ONLY_DYNAMIC_STATUS_SUFFIXES,
    NAS_CARD_ONLY_METRIC_NAMES,
    PRINTER_DETAIL_ONLY_METRICS,
    PRINTER_METRIC_NAMES as PRINTER_METRIC_NAMES,
    STATUS_OPTIONS as STATUS_OPTIONS,
)
from .formatting import (
    _dynamic_mikrotik_metric_label as _dynamic_mikrotik_metric_label,
    _dynamic_nas_metric_label as _dynamic_nas_metric_label,
    _format_duration as _format_duration,
    _format_metric_value as _format_metric_value,
    _format_metric_value_components as _format_metric_value_components,
    _format_metric_values as _format_metric_values,
    _friendly_metric_name as _friendly_metric_name,
    _has_unit as _has_unit,
    _humanize_printer_text as _humanize_printer_text,
    _metric_filter_label as _metric_filter_label,
    _y_axis_label as _y_axis_label,
)

try:
    from components.api import get_json, paged_items, paged_meta
    from components.time_utils import format_wib_timestamp, to_wib_timestamp, wib_date_boundary_to_utc_iso
    from components.ui import normalize_status_label
except ModuleNotFoundError:  # pragma: no cover - supports package imports outside Streamlit's app root
    from dashboard.components.api import get_json, paged_items, paged_meta
    from dashboard.components.time_utils import format_wib_timestamp, to_wib_timestamp, wib_date_boundary_to_utc_iso
    from dashboard.components.ui import normalize_status_label


def _default_device_option_label(devices: list[dict]) -> str:
    """Choose the most useful default device option for the live monitoring page."""
    internet_targets = [device for device in devices if device.get("device_type") == "internet_target"]
    if not internet_targets:
        return "Semua Device"

    preferred_device = next(
        (device for device in internet_targets if "myrepublic" in str(device.get("name", "")).lower()),
        None,
    )
    if preferred_device:
        return format_device_label(preferred_device)

    preferred_device = next(
        (device for device in internet_targets if "isp" in str(device.get("name", "")).lower()),
        None,
    )
    if preferred_device:
        return format_device_label(preferred_device)

    preferred_device = next(
        (device for device in internet_targets if "mikrotik" not in str(device.get("name", "")).lower()),
        None,
    )
    if preferred_device:
        return format_device_label(preferred_device)
    return "Semua Device"


def _should_hide_metric_for_device(metric_name: str, device_type: str | None, device_name: str | None) -> bool:
    """Return whether a metric is irrelevant for the selected device."""
    return is_mikrotik_device(device_type, device_name) and metric_name in INTERNET_ONLY_METRICS


def _filter_metric_names(metric_names: list[str], device_type: str | None, device_name: str | None = None) -> list[str]:
    """Remove metric names that should not appear for the selected device context."""
    return [
        metric_name
        for metric_name in metric_names
        if not _should_hide_metric_for_device(metric_name, device_type, device_name)
        and not (device_type == "printer" and metric_name in PRINTER_DETAIL_ONLY_METRICS)
    ]


def _is_nas_card_only_metric(metric_name: str) -> bool:
    """Return whether a NAS metric should render as a card instead of a chart."""
    metric_name = str(metric_name or "")
    if metric_name in NAS_CARD_ONLY_METRIC_NAMES:
        return True
    if metric_name.startswith(NAS_CARD_ONLY_DYNAMIC_PREFIXES):
        return metric_name.endswith(NAS_CARD_ONLY_DYNAMIC_STATUS_SUFFIXES) or metric_name.startswith("nas_volume:")
    if metric_name.startswith("nas_disk:") and metric_name.endswith(":status"):
        return True
    if metric_name.startswith("nas_disk:") and metric_name.endswith(":temperature_c"):
        return True
    return False


def _default_nas_trend_metrics(metric_names: list[str]) -> list[str]:
    """Return NAS metrics that benefit from trend charts."""
    preferred_metrics = [
        "ping",
        "packet_loss",
        "jitter",
        "cpu_percent",
        "memory_percent",
        "disk_percent",
    ]
    available = set(str(metric_name) for metric_name in metric_names)
    return [metric_name for metric_name in preferred_metrics if metric_name in available]


def _filter_history_rows(
    rows: list[dict],
    device_type_by_id: dict[int, str],
    device_name_by_id: dict[int, str],
) -> list[dict]:
    """Remove history rows that are not relevant for their device type."""
    filtered_rows: list[dict] = []
    for row in rows:
        device_id = int(row.get("device_id", 0) or 0)
        device_type = device_type_by_id.get(device_id)
        device_name = device_name_by_id.get(device_id) or str(row.get("device_name") or "")
        metric_name = str(row.get("metric_name") or "")
        if _should_hide_metric_for_device(metric_name, device_type, device_name):
            continue
        filtered_rows.append(row)
    return filtered_rows


def _prepare_history_frame(history: list[dict], *, sort_desc: bool = True) -> pd.DataFrame:
    """Convert API history rows into a typed DataFrame ready for charts and tables."""
    dataframe = pd.DataFrame(history)
    if dataframe.empty:
        return dataframe

    dataframe["checked_at"] = to_wib_timestamp(dataframe["checked_at"])
    if sort_desc:
        dataframe = dataframe.sort_values("checked_at", ascending=False).copy()
    else:
        dataframe = dataframe.copy()
    metric_names = dataframe["metric_name"].dropna().astype(str).unique()
    metric_label_map = {metric_name: _friendly_metric_name(metric_name) for metric_name in metric_names}
    dataframe["metric_label"] = dataframe["metric_name"].astype(str).map(metric_label_map)
    dataframe["checked_at_wib"] = dataframe["checked_at"].map(format_wib_timestamp)
    dataframe["display_value"] = _format_metric_values(dataframe)
    dataframe["status"] = dataframe["status"].map(normalize_status_label)
    return dataframe


def _fetch_device_history_rows(
    *,
    device_id: int,
    checked_from_date,
    checked_to_date,
    metric_names: list[str] | None = None,
    status: str | None = None,
    max_pages: int | None = None,
    initial_payload: dict | None = None,
) -> list[dict]:
    """Fetch history rows for the selected device and time window."""
    if metric_names:
        unique_metric_names = list(dict.fromkeys(str(metric_name) for metric_name in metric_names))
        if max_pages == 1:
            return _fetch_history_rows_bulk(
                device_id=device_id,
                metric_names=unique_metric_names,
                status=status,
                checked_from_date=checked_from_date,
                checked_to_date=checked_to_date,
                per_metric_limit=500,
            )

        items: list[dict] = []
        for metric_name in unique_metric_names:
            items.extend(
                _fetch_history_pages(
                    device_id=device_id,
                    metric_name=metric_name,
                    status=status,
                    checked_from_date=checked_from_date,
                    checked_to_date=checked_to_date,
                    max_pages=max_pages,
                    initial_payload=initial_payload if len(unique_metric_names) == 1 else None,
                )
            )
        return items

    return _fetch_history_pages(
        device_id=device_id,
        status=status,
        checked_from_date=checked_from_date,
        checked_to_date=checked_to_date,
        max_pages=max_pages,
        initial_payload=initial_payload,
    )


def _history_query_params(
    *,
    device_id: int,
    metric_name: str | None = None,
    status: str | None = None,
    checked_from_date=None,
    checked_to_date=None,
    limit: int = 500,
    offset: int = 0,
    metric_names: list[str] | None = None,
    per_metric_limit: int | None = None,
) -> dict[str, object]:
    """Return history query params for the live monitoring dashboard."""
    query_params: dict[str, object] = {
        "limit": limit,
        "offset": offset,
        "device_id": device_id,
    }
    if metric_name:
        query_params["metric_name"] = metric_name
    if metric_names:
        query_params["metric_names"] = metric_names
    if per_metric_limit is not None:
        query_params["per_metric_limit"] = per_metric_limit
    if status and status != "All":
        query_params["status"] = status
    if checked_from_date:
        query_params["checked_from"] = wib_date_boundary_to_utc_iso(checked_from_date)
    if checked_to_date:
        query_params["checked_to"] = wib_date_boundary_to_utc_iso(checked_to_date, end_of_day=True)
    return query_params


def _fetch_history_pages(
    *,
    device_id: int,
    metric_name: str | None = None,
    status: str | None = None,
    checked_from_date=None,
    checked_to_date=None,
    max_pages: int | None = None,
    initial_payload: dict | None = None,
) -> list[dict]:
    """Fetch paged metric history until the requested row budget is reached."""
    page_size = 500
    offset = 0
    cursor: str | None = None
    items: list[dict] = []
    next_payload = initial_payload

    while True:
        if next_payload is None:
            query_params = _history_query_params(
                device_id=device_id,
                metric_name=metric_name,
                status=status,
                checked_from_date=checked_from_date,
                checked_to_date=checked_to_date,
                limit=page_size,
                offset=offset,
            )
            if cursor:
                query_params.pop("offset", None)
                query_params["cursor"] = cursor
            payload = get_json(f"/metrics/history/paged?{urlencode(query_params, doseq=True)}", {"items": [], "meta": {}})
        else:
            payload = next_payload
            next_payload = None
        page_items = paged_items(payload)
        if not page_items:
            break

        items.extend(page_items)
        meta = paged_meta(payload)
        cursor = meta.get("next_cursor")
        offset += len(page_items)
        total = meta.get("total")
        has_more = bool(meta.get("has_more"))
        if not cursor and (not has_more or total is None or offset >= int(total or 0)):
            break
        if max_pages is not None and offset >= page_size * max_pages:
            break

    return items


def _fetch_history_rows_bulk(
    *,
    device_id: int,
    metric_names: list[str],
    status: str | None = None,
    checked_from_date=None,
    checked_to_date=None,
    per_metric_limit: int = 500,
) -> list[dict]:
    """Fetch multi-metric history rows for the live trend view."""
    if not metric_names:
        return []
    query_params = _history_query_params(
        device_id=device_id,
        metric_names=metric_names,
        status=status,
        checked_from_date=checked_from_date,
        checked_to_date=checked_to_date,
        # Backend applies per-metric limiting when metric_names + per_metric_limit
        # are provided, and still validates `limit` <= 500.
        limit=500,
        offset=0,
        per_metric_limit=per_metric_limit,
    )
    payload = get_json(f"/metrics/history/paged?{urlencode(query_params, doseq=True)}", {"items": [], "meta": {}})
    return list(paged_items(payload))


def _fetch_latest_device_snapshot(device_id: int, limit: int = 500) -> list[dict]:
    """Fetch the latest metric snapshot for one device."""
    payload = get_json(
        f"/metrics/latest-snapshot/paged?{urlencode({'device_id': device_id, 'limit': limit, 'offset': 0})}",
        {"items": [], "meta": {}},
    )
    return list(paged_items(payload))


def _latest_snapshot_frame(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Return latest latest snapshot frame used by dashboard payloads."""
    return dataframe.drop_duplicates(subset=["device_name", "metric_name"]).copy()


def _snapshot_pagination_controls(total_rows: int) -> tuple[int, int]:
    """Return snapshot pagination controls for the live monitoring dashboard."""
    page_size_col, page_col, _ = st.columns([1, 1, 4])
    default_page_size = int(st.session_state.get("history_snapshot_page_size", 10))
    if default_page_size not in [10, 25, 50, 100]:
        default_page_size = 10
    page_size = page_size_col.selectbox(
        "Baris Snapshot",
        options=[10, 25, 50, 100],
        index=[10, 25, 50, 100].index(default_page_size),
        key="history_snapshot_page_size",
    )
    total_pages = max((total_rows - 1) // page_size + 1, 1)
    page_number = page_col.number_input(
        "Halaman Snapshot",
        min_value=1,
        max_value=total_pages,
        value=min(st.session_state.get("history_snapshot_page", 1), total_pages),
        step=1,
        key="history_snapshot_page",
    )
    return int(page_size), int(page_number)


def _paginate_frame(dataframe: pd.DataFrame, *, key_prefix: str, page_size: int = 10) -> pd.DataFrame:
    """Return paginate frame for the live monitoring dashboard."""
    if dataframe.empty:
        return dataframe
    total_rows = len(dataframe)
    total_pages = max((total_rows - 1) // page_size + 1, 1)
    page_key = f"{key_prefix}_page"
    current_page = min(int(st.session_state.get(page_key, 1)), total_pages)
    page_col, meta_col = st.columns([1, 5])
    page_number = page_col.number_input(
        "Halaman Data",
        min_value=1,
        max_value=total_pages,
        value=current_page,
        step=1,
        key=page_key,
    )
    start = (int(page_number) - 1) * page_size
    end = start + page_size
    meta_col.caption(f"Menampilkan {start + 1}-{min(end, total_rows)} dari {total_rows} baris.")
    return dataframe.iloc[start:end].copy()

__all__ = ['_default_device_option_label', '_should_hide_metric_for_device', '_filter_metric_names', '_is_nas_card_only_metric', '_default_nas_trend_metrics', '_filter_history_rows', '_prepare_history_frame', '_fetch_device_history_rows', '_history_query_params', '_fetch_history_pages', '_fetch_history_rows_bulk', '_fetch_latest_device_snapshot', '_latest_snapshot_frame', '_snapshot_pagination_controls', '_paginate_frame']
