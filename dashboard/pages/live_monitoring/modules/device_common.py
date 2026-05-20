"""Shared device-specific live monitoring helpers."""

import pandas as pd


def _latest_metric_snapshot_map(dataframe: pd.DataFrame) -> dict[str, pd.Series]:
    """Return latest latest metric snapshot map used by dashboard payloads."""
    if dataframe.empty:
        return {}
    latest_rows = dataframe.sort_values("checked_at").drop_duplicates(subset=["metric_name"], keep="last")
    return {str(row["metric_name"]): row for _, row in latest_rows.iterrows()}


def _latest_metric_value_from_map(
    latest_map: dict[str, pd.Series],
    metric_name: str,
    default: str = "-",
) -> str:
    """Return latest latest metric value from map used by dashboard payloads."""
    row = latest_map.get(metric_name)
    if row is None:
        return default
    return str(row.get("metric_value") or default)


def _latest_metric_display_from_map(
    latest_map: dict[str, pd.Series],
    metric_name: str,
    default: str = "-",
) -> str:
    """Return latest formatted metric display value from map."""
    row = latest_map.get(metric_name)
    if row is None:
        return default
    return str(row.get("display_value") or row.get("metric_value") or default)


def _nas_volume_capacity_view(latest_map: dict[str, pd.Series]) -> pd.DataFrame:
    """Return latest NAS volume capacity rows grouped by volume."""
    volumes: dict[str, dict[str, object]] = {}
    for metric_name, row in latest_map.items():
        parts = str(metric_name or "").split(":")
        if len(parts) != 3 or parts[0] != "nas_volume":
            continue
        volume_key = parts[1]
        metric_key = parts[2]
        volume = volumes.setdefault(
            volume_key,
            {
                "Volume": volume_key.replace("_", " ").title(),
                "Status": "-",
                "Total": "-",
                "Terpakai": "-",
                "Sisa": "-",
                "Used": "-",
                "Dicek (WIB)": row.get("checked_at_wib"),
            },
        )
        if metric_key == "status":
            volume["Status"] = _latest_metric_display_from_map(latest_map, metric_name)
        elif metric_key == "total_bytes":
            volume["Total"] = _latest_metric_display_from_map(latest_map, metric_name)
        elif metric_key == "used_bytes":
            volume["Terpakai"] = _latest_metric_display_from_map(latest_map, metric_name)
        elif metric_key == "free_bytes":
            volume["Sisa"] = _latest_metric_display_from_map(latest_map, metric_name)
        elif metric_key == "used_percent":
            volume["Used"] = _format_percent(str(row.get("metric_value") or row.get("metric_value_numeric") or ""))
        checked_at = row.get("checked_at_wib")
        if checked_at:
            volume["Dicek (WIB)"] = checked_at
    if not volumes:
        return pd.DataFrame()
    return pd.DataFrame(volumes.values()).sort_values("Volume")


def _format_percent(value: str) -> str:
    """Format percent for the live monitoring dashboard."""
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "-"


def _format_bytes(value: float | int | None) -> str:
    """Format bytes for the live monitoring dashboard."""
    if value is None or pd.isna(value):
        return "-"
    size = float(value)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size) < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return "-"


def _format_mbps(value: float | int | None) -> str:
    """Format mbps for the live monitoring dashboard."""
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2f}"


__all__ = [
    "_latest_metric_snapshot_map",
    "_latest_metric_value_from_map",
    "_latest_metric_display_from_map",
    "_nas_volume_capacity_view",
    "_format_percent",
    "_format_bytes",
    "_format_mbps",
]
