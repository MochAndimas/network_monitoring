"""Live monitoring rendering and table shaping helpers."""


import altair as alt
import pandas as pd
import streamlit as st

from .constants import (
    CHART_WINDOW_OPTIONS,
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
    from components.ui import normalize_status_label, status_priority
except ModuleNotFoundError:  # pragma: no cover - supports package imports outside Streamlit's app root
    from dashboard.components.ui import normalize_status_label, status_priority


def _render_metric_trend_section(
    metric_frame: pd.DataFrame,
    *,
    chart_window_label: str,
    target_column=None,
) -> None:
    """Render metric trend KPIs, charts, and raw history tables."""
    container = target_column if target_column is not None else st
    latest_metric_timestamp = metric_frame["checked_at"].max()
    chart_window_hours = CHART_WINDOW_OPTIONS[chart_window_label]
    chart_window_start = latest_metric_timestamp - pd.Timedelta(hours=chart_window_hours)
    chart_metric_frame = metric_frame[metric_frame["checked_at"] >= chart_window_start].copy()
    if chart_metric_frame.empty:
        chart_metric_frame = metric_frame.copy()

    latest_metric_row = chart_metric_frame.iloc[-1]
    metric_unit = latest_metric_row["unit"]
    metric_name = latest_metric_row["metric_name"]
    metric_device_name = latest_metric_row["device_name"]
    metric_label = _friendly_metric_name(metric_name)
    chart_min = float(chart_metric_frame["metric_value_numeric"].min())
    chart_max = float(chart_metric_frame["metric_value_numeric"].max())
    chart_avg = float(chart_metric_frame["metric_value_numeric"].mean())
    sample_count = int(len(chart_metric_frame))
    previous_value = (
        float(chart_metric_frame["metric_value_numeric"].iloc[-2])
        if sample_count > 1
        else None
    )
    latest_value = float(latest_metric_row["metric_value_numeric"])
    delta_value = latest_value - previous_value if previous_value is not None else None
    trend_text = _trend_direction_text(delta_value)

    unit_suffix = f" ({metric_unit})" if metric_unit else ""
    container.markdown(f"#### {metric_label} - {metric_device_name}")
    container.caption(
        f"Nilai terakhir {_format_metric_value(latest_metric_row)} | "
        f"{trend_text} | "
        f"Rentang {chart_min:.2f} - {chart_max:.2f}{unit_suffix} | "
        f"{sample_count} sampel ({chart_window_label})"
    )
    stat_col1, stat_col2, stat_col3, stat_col4 = container.columns(4)
    _render_stat_card(stat_col1, "Nilai Terakhir", _format_metric_value(latest_metric_row))
    _render_stat_card(stat_col2, "Arah", trend_text)
    _render_stat_card(stat_col3, "Rata-rata", _format_metric_numeric(chart_avg, metric_unit))
    _render_stat_card(stat_col4, "Status", _status_label_for_display(latest_metric_row["status"]))

    chart_title = f"Tren {metric_label} - {metric_device_name}"
    avg_frame = pd.DataFrame([{"line_label": "Rata-rata", "line_value": chart_avg}])
    line_chart = (
        alt.Chart(chart_metric_frame)
        .mark_line(point=True)
        .encode(
            x=alt.X(
                "checked_at:T",
                title="Waktu Check (WIB)",
                axis=alt.Axis(format="%H:%M", labelAngle=0),
            ),
            y=alt.Y(
                "metric_value_numeric:Q",
                title=_y_axis_label(metric_name, metric_unit),
            ),
            tooltip=[
                alt.Tooltip("checked_at_wib:N", title="Dicek"),
                alt.Tooltip("device_name:N", title="Device"),
                alt.Tooltip("metric_label:N", title="Metrik"),
                alt.Tooltip("display_value:N", title="Nilai"),
                alt.Tooltip("status:N", title="Status"),
            ],
        )
    )
    reference_lines = (
        alt.Chart(avg_frame)
        .mark_rule(strokeDash=[6, 4], strokeWidth=1.5)
        .encode(
            y=alt.Y("line_value:Q"),
            color=alt.Color(
                "line_label:N",
                title="Referensi",
                scale=alt.Scale(
                    domain=["Rata-rata"],
                    range=["#22c55e"],
                ),
            ),
            tooltip=[
                alt.Tooltip("line_label:N", title="Garis"),
                alt.Tooltip("line_value:Q", title="Nilai", format=".2f"),
            ],
        )
    )
    chart = (line_chart + reference_lines).properties(title=chart_title, height=280)
    container.altair_chart(chart, width="stretch")


def _render_stat_card(column, label: str, value: str | int, *, compact: bool = False) -> None:
    """Render stat card for the live monitoring dashboard."""
    with column.container(border=True):
        st.metric(label, value)


def _status_counts_frame(
    latest_snapshot_status_summary: dict[str, int],
    fallback_frame: pd.DataFrame,
) -> pd.DataFrame:
    """Return status counts frame for the live monitoring dashboard."""
    if latest_snapshot_status_summary:
        status_counts = pd.DataFrame(
            [{"status": normalize_status_label(status), "Jumlah": count} for status, count in latest_snapshot_status_summary.items()]
        )
    elif not fallback_frame.empty:
        counts = fallback_frame["status"].fillna("Unknown").map(normalize_status_label).value_counts()
        status_counts = pd.DataFrame({"status": counts.index.tolist(), "Jumlah": counts.values.tolist()})
    else:
        status_counts = pd.DataFrame(columns=["status", "Jumlah"])
    if status_counts.empty:
        return status_counts
    status_counts["priority"] = status_counts["status"].map(status_priority)
    return status_counts.sort_values(["priority", "Jumlah", "status"], ascending=[True, False, True]).reset_index(drop=True)


def _status_color_scale() -> alt.Scale:
    """Return status color scale for the live monitoring dashboard."""
    return alt.Scale(
        domain=["Down", "Error", "Warning", "Unknown", "Active", "Resolved", "OK", "Up"],
        range=["#dc2626", "#ef4444", "#f59e0b", "#6b7280", "#3b82f6", "#10b981", "#22c55e", "#16a34a"],
    )


def _health_score_percent(status_counts: pd.DataFrame) -> int:
    """Return health score percent for the live monitoring dashboard."""
    if status_counts.empty:
        return 0
    total = int(status_counts["Jumlah"].sum())
    if total <= 0:
        return 0
    weighted_score = 0.0
    status_weights = {
        "Up": 1.0,
        "OK": 1.0,
        "Resolved": 0.8,
        "Active": 0.6,
        "Warning": 0.5,
        "Unknown": 0.3,
        "Error": 0.0,
        "Down": 0.0,
    }
    for _, row in status_counts.iterrows():
        weighted_score += float(row.get("Jumlah", 0) or 0) * float(status_weights.get(str(row.get("status") or ""), 0.4))
    return max(0, min(100, round((weighted_score / total) * 100)))


def _entity_volume_frame(dataframe: pd.DataFrame, column_name: str, label_name: str, top_n: int = 6) -> pd.DataFrame:
    """Return entity volume frame for the live monitoring dashboard."""
    if dataframe.empty or column_name not in dataframe.columns:
        return pd.DataFrame(columns=[label_name, "Jumlah"])
    grouped = (
        dataframe[column_name]
        .fillna("-")
        .astype(str)
        .value_counts()
        .head(top_n)
        .reset_index()
    )
    grouped.columns = [label_name, "Jumlah"]
    return grouped


def _recent_anomaly_frame(dataframe: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """Return recent anomaly frame for the live monitoring dashboard."""
    if dataframe.empty:
        return pd.DataFrame()
    anomaly_statuses = {"Warning", "Down", "Error"}
    anomaly_frame = dataframe[dataframe["status"].isin(anomaly_statuses)].copy()
    if anomaly_frame.empty:
        return anomaly_frame
    return anomaly_frame.sort_values("checked_at", ascending=False).head(top_n)


def _format_metric_numeric(value: float | int | None, unit: str | None = None) -> str:
    """Format metric numeric for the live monitoring dashboard."""
    if value is None or pd.isna(value):
        return "-"
    suffix = f" {unit}" if unit else ""
    return f"{float(value):.2f}{suffix}"


def _format_celsius(value: object) -> str:
    """Format Celsius values for compact NAS cards."""
    numeric_value = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric_value):
        return "-"
    return f"{float(numeric_value):.2f} C"


def _trend_direction_text(delta_value: float | None) -> str:
    """Return trend direction text for the live monitoring dashboard."""
    if delta_value is None or pd.isna(delta_value):
        return "Stabil (data awal)"
    if abs(float(delta_value)) < 1e-9:
        return "Stabil (0)"
    direction = "Naik" if float(delta_value) > 0 else "Turun"
    return f"{direction} {abs(float(delta_value)):.2f}"


def _metric_kpi_summary(metric_frame: pd.DataFrame) -> dict[str, object]:
    """Return metric kpi summary for the live monitoring dashboard."""
    if metric_frame.empty:
        return {}
    ordered = metric_frame.sort_values("checked_at").copy()
    latest_row = ordered.iloc[-1]
    latest_value_numeric = pd.to_numeric(latest_row.get("metric_value_numeric"), errors="coerce")
    previous_value = (
        float(ordered["metric_value_numeric"].iloc[-2])
        if len(ordered) > 1 and pd.notna(ordered["metric_value_numeric"].iloc[-2])
        else None
    )
    delta_value = (
        float(latest_value_numeric) - previous_value
        if pd.notna(latest_value_numeric) and previous_value is not None
        else None
    )
    numeric_series = pd.to_numeric(ordered["metric_value_numeric"], errors="coerce")
    unit = latest_row.get("unit")
    return {
        "metric_label": _friendly_metric_name(str(latest_row.get("metric_name") or "")),
        "device_name": str(latest_row.get("device_name") or "-"),
        "latest_display": _format_metric_value(latest_row),
        "latest_numeric": float(latest_value_numeric) if pd.notna(latest_value_numeric) else None,
        "avg": float(numeric_series.mean()) if numeric_series.notna().any() else None,
        "min": float(numeric_series.min()) if numeric_series.notna().any() else None,
        "max": float(numeric_series.max()) if numeric_series.notna().any() else None,
        "count": int(len(ordered)),
        "status": _status_label_for_display(latest_row.get("status")),
        "delta": delta_value,
        "unit": str(unit) if unit else None,
    }


def _raw_history_view(raw_history_frame: pd.DataFrame, *, metric_selected: bool) -> pd.DataFrame:
    """Return raw history view for the live monitoring dashboard."""
    if raw_history_frame.empty:
        return pd.DataFrame(columns=["Dicek (WIB)", "Nilai", "Status", "Device", "Metrik"])
    if not metric_selected:
        return raw_history_frame[
            ["checked_at_wib", "device_name", "metric_label", "display_value", "status"]
        ].rename(
            columns={
                "checked_at_wib": "Dicek (WIB)",
                "device_name": "Device",
                "metric_label": "Metrik",
                "display_value": "Nilai",
                "status": "Status",
            }
        )

    enriched = raw_history_frame.sort_values("checked_at").copy()
    enriched["numeric_value"] = pd.to_numeric(enriched["metric_value_numeric"], errors="coerce")
    enriched["delta_numeric"] = enriched["numeric_value"].diff()
    enriched["Nilai Numerik"] = enriched.apply(
        lambda row: _format_metric_numeric(row.get("numeric_value"), row.get("unit")),
        axis=1,
    )
    enriched["Perubahan"] = enriched["delta_numeric"].map(
        lambda value: "-" if pd.isna(value) else f"{value:+.2f}"
    )
    enriched["Catatan"] = "-"
    numeric_series = enriched["numeric_value"]
    if numeric_series.notna().any():
        max_value = float(numeric_series.max())
        min_value = float(numeric_series.min())
        enriched.loc[numeric_series.eq(max_value), "Catatan"] = "Puncak window"
        enriched.loc[numeric_series.eq(min_value), "Catatan"] = "Terendah window"
    enriched = enriched.sort_values("checked_at", ascending=False)
    return enriched[
        ["checked_at_wib", "display_value", "Nilai Numerik", "Perubahan", "status", "device_name", "metric_label", "Catatan"]
    ].rename(
        columns={
            "checked_at_wib": "Dicek (WIB)",
            "display_value": "Nilai",
            "status": "Status",
            "device_name": "Device",
            "metric_label": "Metrik",
        }
    )


def _status_label_for_display(status_value: object) -> str:
    """Return status label for display for the live monitoring dashboard."""
    normalized = str(status_value or "").strip().lower()
    if normalized in {"down", "error"}:
        return f"Tinggi | {normalize_status_label(normalized)}"
    if normalized == "warning":
        return f"Sedang | {normalize_status_label(normalized)}"
    if normalized in {"up", "ok"}:
        return f"Normal | {normalize_status_label(normalized)}"
    return f"Info | {normalize_status_label(normalized)}"


def _non_numeric_metric_timeline(metric_frame: pd.DataFrame) -> pd.DataFrame:
    """Return non numeric metric timeline for the live monitoring dashboard."""
    if metric_frame.empty:
        return pd.DataFrame(columns=["Dicek (WIB)", "Nilai", "Status", "Device", "Metrik"])
    ordered = metric_frame.sort_values("checked_at", ascending=False).copy()
    ordered["status_display"] = ordered["status"].map(_status_label_for_display)
    return ordered[
        ["checked_at_wib", "display_value", "status_display", "device_name", "metric_label"]
    ].rename(
        columns={
            "checked_at_wib": "Dicek (WIB)",
            "display_value": "Nilai",
            "status_display": "Status",
            "device_name": "Device",
            "metric_label": "Metrik",
        }
    )

__all__ = ['_render_metric_trend_section', '_render_stat_card', '_status_counts_frame', '_status_color_scale', '_health_score_percent', '_entity_volume_frame', '_recent_anomaly_frame', '_format_metric_numeric', '_format_celsius', '_trend_direction_text', '_metric_kpi_summary', '_raw_history_view', '_status_label_for_display', '_non_numeric_metric_timeline']
