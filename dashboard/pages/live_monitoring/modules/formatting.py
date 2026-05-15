"""Formatting helpers used by live monitoring views."""

import pandas as pd

from .constants import METRIC_LABELS


def _format_metric_value(row: pd.Series) -> str:
    """Format one metric row value for display in Streamlit tables."""
    return _format_metric_value_components(
        metric_name=str(row.get("metric_name") or ""),
        metric_value=row.get("metric_value"),
        metric_value_numeric=row.get("metric_value_numeric"),
        unit=row.get("unit"),
    )


def _format_metric_value_components(
    *,
    metric_name: str,
    metric_value,
    metric_value_numeric,
    unit,
) -> str:
    """Format a metric value using metric-specific unit and status conventions."""
    metric_name = str(metric_name or "")
    if metric_name == "printer_uptime_seconds" and pd.notna(metric_value_numeric):
        return _format_duration(pd.Timedelta(seconds=float(metric_value_numeric)))
    if metric_name == "nas_uptime_seconds" and pd.notna(metric_value_numeric):
        return _format_duration(pd.Timedelta(seconds=float(metric_value_numeric)))
    if metric_name == "printer_total_pages" and pd.notna(metric_value_numeric):
        return f"{int(metric_value_numeric):,} pages"
    if metric_name == "printer_ink_status":
        return _humanize_printer_text(str(metric_value or "-"))
    if metric_name in {"printer_status", "printer_error_state", "printer_paper_status"}:
        return _humanize_printer_text(str(metric_value or "-"))
    if metric_name in {"nas_system_status", "nas_power_status"} or metric_name.endswith(":status"):
        return _humanize_printer_text(str(metric_value or "-"))
    if str(unit).lower() == "bytes" and pd.notna(metric_value_numeric):
        return _format_bytes(float(metric_value_numeric))
    unit_suffix = f" {unit}" if _has_unit(unit) else ""
    return f"{metric_value}{unit_suffix}"


def _friendly_metric_name(metric_name: str) -> str:
    """Return a human-friendly label for static and dynamic metric names."""
    dynamic_label = _dynamic_mikrotik_metric_label(metric_name)
    if dynamic_label:
        return dynamic_label
    dynamic_label = _dynamic_nas_metric_label(metric_name)
    if dynamic_label:
        return dynamic_label
    return METRIC_LABELS.get(metric_name, (metric_name.replace("_", " ").title(), ""))[0]


def _metric_filter_label(metric_name: str) -> str:
    """Return metric filter label for the live monitoring dashboard."""
    if metric_name == "All Metrics":
        return "Semua Metrik"
    return f"{_friendly_metric_name(metric_name)} ({metric_name})"


def _dynamic_mikrotik_metric_label(metric_name: str) -> str | None:
    """Return a readable label for dynamic Mikrotik metric names."""
    parts = str(metric_name or "").split(":")
    if len(parts) < 3:
        return None
    category = parts[0]
    name = parts[1].replace("_", " ").title()
    metric_key = parts[-1]
    metric_labels = {
        "rx_bytes": "RX Bytes",
        "tx_bytes": "TX Bytes",
        "rx_mbps": "RX Mbps",
        "tx_mbps": "TX Mbps",
        "packets": "Packets",
        "bytes": "Bytes",
        "pps": "Packets/s",
        "mbps": "Mbps",
    }
    suffix = metric_labels.get(metric_key, metric_key.replace("_", " ").title())
    if category == "interface":
        return f"Interface {name} {suffix}"
    if category == "queue":
        return f"Queue {name} {suffix}"
    if category == "firewall" and len(parts) >= 4:
        section = parts[1].upper()
        rule = parts[2].replace("_", " ").title()
        return f"Firewall {section} {rule} {suffix}"
    return None


def _dynamic_nas_metric_label(metric_name: str) -> str | None:
    """Return a readable label for dynamic NAS metric names."""
    parts = str(metric_name or "").split(":")
    if len(parts) != 3 or parts[0] not in {"nas_volume", "nas_raid", "nas_disk", "nas_fan"}:
        return None
    entity = parts[1].replace("_", " ").title()
    metric_key = parts[2]
    metric_labels = {
        "status": "Status",
        "used_percent": "Used",
        "total_bytes": "Total",
        "used_bytes": "Used",
        "free_bytes": "Free",
        "temperature_c": "Temperature",
    }
    suffix = metric_labels.get(metric_key, metric_key.replace("_", " ").title())
    category_labels = {
        "nas_volume": "Volume",
        "nas_raid": "Storage Pool",
        "nas_disk": "Disk",
        "nas_fan": "Fan",
    }
    return f"NAS {category_labels[parts[0]]} {entity} {suffix}"


def _humanize_printer_text(value: str) -> str:
    """Return printer-oriented text with underscores and commas formatted for people."""
    normalized = str(value or "-").replace("_", " ").replace(",", ", ")
    return normalized.title() if normalized not in {"-", ""} else "-"


def _y_axis_label(metric_name: str, unit: str | None) -> str:
    """Return chart axis label for a metric."""
    label = _friendly_metric_name(metric_name)
    if unit:
        return f"{label} ({unit})"
    return label


def _format_duration(delta: pd.Timedelta | None) -> str:
    """Format a duration compactly for table and card displays."""
    if delta is None or pd.isna(delta):
        return "-"
    total_seconds = max(int(delta.total_seconds()), 0)
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}j")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}dtk")
    return " ".join(parts)


def _format_metric_values(dataframe: pd.DataFrame) -> pd.Series:
    """Vector-ish wrapper for formatting metric values in a dataframe."""
    if dataframe.empty:
        return pd.Series(dtype="object")
    return dataframe.apply(_format_metric_value, axis=1)


def _has_unit(unit: object) -> bool:
    """Return whether a metric unit is useful to display."""
    return bool(pd.notna(unit) and str(unit).strip())


def _format_metric_numeric(value: float | int | None, unit: str | None = None) -> str:
    """Format a numeric metric value for compact cards."""
    if value is None or pd.isna(value):
        return "-"
    if unit == "bytes":
        return _format_bytes(value)
    return f"{float(value):.2f}{unit or ''}"


def _format_celsius(value: object) -> str:
    """Format a Celsius value."""
    if value is None or pd.isna(value):
        return "-"
    return f"{float(str(value)):.1f}C"


def _trend_direction_text(delta_value: float | None) -> str:
    """Return trend direction text from a numeric delta."""
    if delta_value is None or pd.isna(delta_value):
        return "stabil"
    if delta_value > 0:
        return "naik"
    if delta_value < 0:
        return "turun"
    return "stabil"


def _status_label_for_display(status_value: object) -> str:
    """Format a status value for display."""
    status = str(status_value or "unknown")
    return status.replace("_", " ").title()


def _format_percent(value: str) -> str:
    """Format a percent-like string with a percent sign when needed."""
    normalized = str(value or "-").strip()
    if normalized in {"", "-"}:
        return "-"
    return normalized if normalized.endswith("%") else f"{normalized}%"


def _format_bytes(value: float | int | None) -> str:
    """Format bytes into a human-readable binary unit."""
    if value is None or pd.isna(value):
        return "-"
    size = float(value)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def _format_mbps(value: float | int | None) -> str:
    """Format Mbps values for Mikrotik tables."""
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2f} Mbps"


__all__ = [
    "_dynamic_mikrotik_metric_label",
    "_dynamic_nas_metric_label",
    "_format_bytes",
    "_format_celsius",
    "_format_duration",
    "_format_mbps",
    "_format_metric_numeric",
    "_format_metric_value",
    "_format_metric_value_components",
    "_format_metric_values",
    "_format_percent",
    "_friendly_metric_name",
    "_has_unit",
    "_humanize_printer_text",
    "_metric_filter_label",
    "_status_label_for_display",
    "_trend_direction_text",
    "_y_axis_label",
]
