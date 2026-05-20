"""Live Monitoring body section renderers."""

from collections.abc import Callable
from typing import Any, cast

import streamlit as st

from dashboard.pages.live_monitoring.helpers import (
    PRINTER_METRIC_NAMES,
    _default_mikrotik_trend_metrics,
    _default_nas_trend_metrics,
    _entity_volume_frame,
    _fetch_latest_device_snapshot,
    _filter_history_rows,
    _filter_metric_names,
    _format_metric_numeric,
    _friendly_metric_name,
    _is_dynamic_mikrotik_metric,
    _is_nas_card_only_metric,
    _metric_kpi_summary,
    _non_numeric_metric_timeline,
    _paginate_frame,
    _raw_history_view,
    _recent_anomaly_frame,
    _render_metric_trend_section,
    _render_mikrotik_history_section,
    _render_nas_history_section,
    _render_printer_history_section,
    _render_stat_card,
    _snapshot_pagination_controls,
    _status_color_scale,
    _status_label_for_display,
    _trend_direction_text,
    alt,
    format_wib_timestamp,
    paged_items,
    pd,
)


def render_history_overview_sections(
    *,
    summary_container: Any,
    snapshot_container: Any,
    status_container: Any,
    auto_refresh: bool,
    interval_seconds: int,
    selected_device: str,
    selected_device_id: int | None,
    selected_metric: str,
    checked_from_date: Any,
    checked_to_date: Any,
    chart_window_label: str,
    history_meta: dict,
    summary_frame: pd.DataFrame,
    summary_latest_timestamp: Any,
    latest_per_series: pd.DataFrame,
    snapshot_meta: dict,
    status_counts: pd.DataFrame,
    health_score: int,
    anomaly_count: int,
    dataframe: pd.DataFrame,
) -> None:
    """Render summary, latest snapshot, and insight sections."""
    with summary_container:
        st.markdown("### Ringkasan Eksekutif")
        if selected_device_id is not None:
            st.caption(f"Ringkasan cepat untuk device terpilih: {selected_device}.")
        else:
            st.caption("Ringkasan cepat untuk melihat kondisi keseluruhan sebelum masuk ke investigasi detail.")
        summary_col1, summary_col2, summary_col3, summary_col4, summary_col5 = st.columns(5)
        _render_stat_card(summary_col1, "Total Data", int(len(summary_frame)))
        _render_stat_card(summary_col2, "Device Terpantau", int(summary_frame["device_name"].nunique()))
        _render_stat_card(summary_col3, "Metrik Aktif", int(summary_frame["metric_name"].nunique()))
        _render_stat_card(summary_col4, "Anomali Aktif", anomaly_count)
        _render_stat_card(summary_col5, "Skor Kesehatan", f"{health_score}%")
        st.caption(f"Pengecekan terakhir pada {format_wib_timestamp(summary_latest_timestamp)} WIB.")

    with snapshot_container:
        st.markdown("### Snapshot Terbaru")
        st.caption(
            f"Menampilkan {len(latest_per_series)} dari total {snapshot_meta.get('total', len(latest_per_series))} metrik terakhir."
        )
        snapshot_view = latest_per_series[
            ["device_name", "metric_label", "display_value", "uptime", "status", "checked_at_wib"]
        ].rename(
            columns={
                "device_name": "Device",
                "metric_label": "Metrik",
                "display_value": "Nilai Terakhir",
                "uptime": "Uptime",
                "status": "Status",
                "checked_at_wib": "Dicek (WIB)",
            }
        )
        snapshot_view["Status"] = snapshot_view["Status"].map(_status_label_for_display)
        st.dataframe(
            snapshot_view,
            width="stretch",
            hide_index=True,
            column_config={
                "Device": st.column_config.TextColumn("Device", width="medium"),
                "Metrik": st.column_config.TextColumn("Metrik", width="medium"),
                "Nilai Terakhir": st.column_config.TextColumn("Nilai Terakhir", width="small"),
                "Uptime": st.column_config.TextColumn("Uptime", width="small"),
                "Status": st.column_config.TextColumn("Status", width="small"),
                "Dicek (WIB)": st.column_config.TextColumn("Dicek (WIB)", width="medium"),
            },
        )
        _snapshot_pagination_controls(int(snapshot_meta.get("total", len(latest_per_series))))

    with status_container:
        st.markdown("### Insight Analisis")
        insight_base_frame = dataframe.copy()
        if selected_metric != "All Metrics":
            insight_base_frame = insight_base_frame[
                insight_base_frame["metric_name"].astype(str) == str(selected_metric)
            ].copy()
            st.caption(f"Insight difokuskan untuk metrik `{_friendly_metric_name(selected_metric)}`.")
        insight_col1, insight_col2 = st.columns([2, 1])
        if status_counts.empty:
            insight_col1.info("Belum ada status device untuk diringkas pada rentang ini.")
        else:
            status_chart = (
                alt.Chart(status_counts)
                .mark_arc(innerRadius=55)
                .encode(
                    theta=alt.Theta("Jumlah:Q", title="Jumlah"),
                    color=alt.Color("status:N", title="Status", scale=_status_color_scale()),
                    tooltip=[
                        alt.Tooltip("status:N", title="Status"),
                        alt.Tooltip("Jumlah:Q", title="Jumlah"),
                    ],
                    order=alt.Order("priority:Q", sort="ascending"),
                )
                .properties(height=260)
            )
            insight_col1.altair_chart(status_chart, width="stretch")

        with insight_col2:
            if not status_counts.empty:
                status_view = status_counts[["status", "Jumlah"]].copy()
                status_view["Status"] = status_view["status"].map(_status_label_for_display)
                status_view = status_view[["Status", "Jumlah"]]
            else:
                status_view = pd.DataFrame(columns=["Status", "Jumlah"])
            st.dataframe(
                status_view,
                width="stretch",
                hide_index=True,
                column_config={
                    "Status": st.column_config.TextColumn("Status", width="small"),
                    "Jumlah": st.column_config.NumberColumn("Jumlah", width="small", format="%d"),
                },
            )

        top_device_frame = _entity_volume_frame(insight_base_frame, "device_name", "Device", top_n=6)
        top_col1, top_col2 = st.columns(2)
        top_col1.markdown("#### Device Paling Aktif")
        top_col1.dataframe(
            top_device_frame,
            width="stretch",
            hide_index=True,
            column_config={
                "Device": st.column_config.TextColumn("Device", width="medium"),
                "Jumlah": st.column_config.NumberColumn("Jumlah", width="small", format="%d"),
            },
        )
        if selected_metric != "All Metrics":
            top_status_frame = (
                insight_base_frame["status"]
                .map(_status_label_for_display)
                .value_counts()
                .head(6)
                .rename_axis("Status")
                .reset_index(name="Jumlah")
                if not insight_base_frame.empty
                else pd.DataFrame(columns=["Status", "Jumlah"])
            )
            top_col2.markdown("#### Status Terbanyak")
            top_col2.dataframe(
                top_status_frame,
                width="stretch",
                hide_index=True,
                column_config={
                    "Status": st.column_config.TextColumn("Status", width="medium"),
                    "Jumlah": st.column_config.NumberColumn("Jumlah", width="small", format="%d"),
                },
            )
        else:
            top_metric_frame = _entity_volume_frame(insight_base_frame, "metric_label", "Metrik", top_n=6)
            top_col2.markdown("#### Metrik Paling Sering Muncul")
            top_col2.dataframe(
                top_metric_frame,
                width="stretch",
                hide_index=True,
                column_config={
                    "Metrik": st.column_config.TextColumn("Metrik", width="medium"),
                    "Jumlah": st.column_config.NumberColumn("Jumlah", width="small", format="%d"),
                },
            )

        anomaly_frame = _recent_anomaly_frame(insight_base_frame)
        if not anomaly_frame.empty:
            st.markdown("#### Anomali Terbaru")
            anomaly_view = anomaly_frame[
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
            anomaly_view["Status"] = anomaly_view["Status"].map(_status_label_for_display)
            st.dataframe(
                anomaly_view,
                width="stretch",
                hide_index=True,
                column_config={
                    "Dicek (WIB)": st.column_config.TextColumn("Dicek (WIB)", width="medium"),
                    "Device": st.column_config.TextColumn("Device", width="medium"),
                    "Metrik": st.column_config.TextColumn("Metrik", width="medium"),
                    "Nilai": st.column_config.TextColumn("Nilai", width="small"),
                    "Status": st.column_config.TextColumn("Status", width="small"),
                },
            )


def render_device_detail_sections(
    *,
    history_context: dict,
    device_type_by_id: dict[int, str],
    device_name_by_id: dict[int, str],
    selected_device_id: int | None,
    selected_device_type: str | None,
    selected_device_record: dict | None,
    selected_metric: str,
    selected_is_mikrotik: bool,
    selected_device_history: list[dict],
    full_device_history: list[dict],
    checked_from_date: Any,
    checked_to_date: Any,
    status_value: str,
    chart_window_label: str,
    dataframe: pd.DataFrame,
    prepare_history_frame: Callable[..., pd.DataFrame],
) -> None:
    """Render selected-device health, trend, and raw-history sections."""
    if selected_is_mikrotik:
        assert selected_device_id is not None
        selected_device_snapshot_payload = history_context.get("selected_device_snapshot", {"items": [], "meta": {}})
        mikrotik_snapshot = _filter_history_rows(
            paged_items(selected_device_snapshot_payload),
            device_type_by_id,
            device_name_by_id,
        )
        if not mikrotik_snapshot:
            mikrotik_snapshot = _filter_history_rows(
                _fetch_latest_device_snapshot(selected_device_id),
                device_type_by_id,
                device_name_by_id,
            )
        mikrotik_history_frame = prepare_history_frame(mikrotik_snapshot, sort_desc=False)
        _render_mikrotik_history_section(mikrotik_history_frame)

    if selected_device_id is not None and selected_device_type == "printer":
        printer_history = [
            row for row in selected_device_history if str(row.get("metric_name") or "") in PRINTER_METRIC_NAMES
        ]
        printer_history_frame = prepare_history_frame(printer_history, sort_desc=False)
        _render_printer_history_section(printer_history_frame)

    if selected_device_id is not None and selected_device_type == "nas":
        nas_history_frame = prepare_history_frame(selected_device_history, sort_desc=False)
        _render_nas_history_section(nas_history_frame)

    trend_heading = "### Tren Metrik Bergerak" if selected_device_type == "nas" else "### Tren Metrik"
    st.markdown(trend_heading)
    if selected_device_id is None:
        st.info("Pilih satu device untuk menampilkan grafik tren.")
        return

    device_history_frame = prepare_history_frame(full_device_history, sort_desc=False)
    if device_history_frame.empty:
        st.info("Belum ada history lengkap untuk device ini pada rentang waktu terpilih.")
        return
    dataframe_desc = dataframe.sort_values("checked_at", ascending=False).copy()
    device_history_frame_desc = device_history_frame.sort_values("checked_at", ascending=False).copy()

    available_metric_names = sorted(device_history_frame["metric_name"].dropna().unique().tolist())
    if selected_device_type == "nas" and selected_metric == "All Metrics":
        metric_names_to_render = _default_nas_trend_metrics(available_metric_names)
    elif selected_is_mikrotik and selected_metric == "All Metrics":
        metric_names_to_render = _default_mikrotik_trend_metrics(available_metric_names)
    else:
        metric_names_to_render = [selected_metric] if selected_metric != "All Metrics" else available_metric_names
    metric_names_to_render = _filter_metric_names(
        metric_names_to_render,
        selected_device_type,
        selected_device_record.get("name") if selected_device_record else None,
    )
    if selected_is_mikrotik and selected_metric == "All Metrics":
        metric_names_to_render = [
            metric_name for metric_name in metric_names_to_render if not _is_dynamic_mikrotik_metric(metric_name)
        ]
    if selected_device_type == "nas":
        if selected_metric == "All Metrics":
            metric_names_to_render = [
                metric_name for metric_name in metric_names_to_render if not _is_nas_card_only_metric(metric_name)
            ]
        elif _is_nas_card_only_metric(str(selected_metric)):
            selected_metric_frame = device_history_frame[
                device_history_frame["metric_name"].astype(str) == str(selected_metric)
            ].copy()
            latest_row = selected_metric_frame.sort_values("checked_at").iloc[-1] if not selected_metric_frame.empty else None
            st.info("Metrik ini stabil dan ditampilkan sebagai kartu, bukan grafik tren.")
            if latest_row is not None:
                card_col1, card_col2, card_col3 = st.columns(3)
                _render_stat_card(card_col1, _friendly_metric_name(str(selected_metric)), str(latest_row.get("display_value") or "-"))
                _render_stat_card(card_col2, "Status", _status_label_for_display(latest_row.get("status")))
                _render_stat_card(card_col3, "Dicek (WIB)", str(latest_row.get("checked_at_wib") or "-"))
            return
    if selected_metric != "All Metrics":
        selected_metric_frame = device_history_frame[
            device_history_frame["metric_name"].astype(str) == str(selected_metric)
        ].copy()
    else:
        selected_metric_frame = pd.DataFrame()
    rendered_metric_frames: list[pd.DataFrame] = []
    metric_frame_by_name = {
        str(metric_name): metric_frame
        for metric_name, metric_frame in device_history_frame.groupby(device_history_frame["metric_name"].astype(str))
    }
    for metric_name in metric_names_to_render:
        if selected_device_type == "nas" and _is_nas_card_only_metric(str(metric_name)):
            continue
        metric_series_frame = metric_frame_by_name.get(str(metric_name))
        if metric_series_frame is None:
            continue
        metric_series_frame = metric_series_frame.dropna(subset=["metric_value_numeric"]).sort_values("checked_at").copy()
        if metric_series_frame.empty:
            continue
        rendered_metric_frames.append(metric_series_frame)

    if not rendered_metric_frames:
        if selected_metric != "All Metrics" and not selected_metric_frame.empty:
            st.info("Metrik ini tidak punya nilai numerik. Menampilkan timeline status dan nilai terbaru.")
            st.markdown("#### Timeline Nilai Non-Numerik")
            non_numeric_timeline = _non_numeric_metric_timeline(selected_metric_frame)
            st.dataframe(
                non_numeric_timeline,
                width="stretch",
                hide_index=True,
                column_config={
                    "Dicek (WIB)": st.column_config.TextColumn("Dicek (WIB)", width="medium"),
                    "Nilai": st.column_config.TextColumn("Nilai", width="medium"),
                    "Status": st.column_config.TextColumn("Status", width="small"),
                    "Device": st.column_config.TextColumn("Device", width="medium"),
                    "Metrik": st.column_config.TextColumn("Metrik", width="medium"),
                },
            )
            return
        st.info("Belum ada data numerik untuk kombinasi device dan metrik ini.")
        return

    if selected_metric != "All Metrics" and rendered_metric_frames:
        selected_metric_summary = _metric_kpi_summary(rendered_metric_frames[0])
        if selected_metric_summary:
            st.markdown("#### Ringkasan Metrik Terpilih")
            st.caption(
                f"{selected_metric_summary['metric_label']} pada {selected_metric_summary['device_name']} - "
                f"{selected_metric_summary['count']} sampel pada rentang terpilih."
            )
            selected_col1, selected_col2, selected_col3, selected_col4, selected_col5, selected_col6 = st.columns(6)
            _render_stat_card(selected_col1, "Nilai Terakhir", str(selected_metric_summary["latest_display"]))
            _render_stat_card(
                selected_col2,
                "Arah Tren",
                _trend_direction_text(cast(float | None, selected_metric_summary.get("delta"))),
            )
            _render_stat_card(
                selected_col3,
                "Rata-rata",
                _format_metric_numeric(
                    cast(float | int | None, selected_metric_summary.get("avg")),
                    str(selected_metric_summary.get("unit") or ""),
                ),
            )
            _render_stat_card(
                selected_col4,
                "Minimum",
                _format_metric_numeric(
                    cast(float | int | None, selected_metric_summary.get("min")),
                    str(selected_metric_summary.get("unit") or ""),
                ),
            )
            _render_stat_card(
                selected_col5,
                "Maksimum",
                _format_metric_numeric(
                    cast(float | int | None, selected_metric_summary.get("max")),
                    str(selected_metric_summary.get("unit") or ""),
                ),
            )
            _render_stat_card(selected_col6, "Status Terakhir", str(selected_metric_summary["status"]))

    chart_rows = [rendered_metric_frames[i:i + 1] for i in range(0, len(rendered_metric_frames), 1)]
    for row_frames in chart_rows:
        chart_columns = st.columns(1)
        for col_index, metric_frame in enumerate(row_frames):
            _render_metric_trend_section(
                metric_frame,
                chart_window_label=chart_window_label,
                target_column=chart_columns[col_index],
            )

    st.markdown("### Riwayat Detail")
    if selected_device_id is not None and selected_device_type == "printer":
        raw_history_frame = device_history_frame_desc if not device_history_frame.empty else dataframe_desc
    elif selected_is_mikrotik and selected_metric == "All Metrics":
        raw_history_frame = dataframe_desc
    else:
        raw_history_frame = pd.concat(rendered_metric_frames, ignore_index=True).sort_values("checked_at", ascending=False)
    raw_view = _raw_history_view(raw_history_frame, metric_selected=selected_metric != "All Metrics")
    if "Status" in raw_view.columns:
        raw_view["Status"] = raw_view["Status"].map(_status_label_for_display)
    paged_raw_view = _paginate_frame(raw_view, key_prefix="history_raw", page_size=10)
    st.dataframe(
        paged_raw_view,
        width="stretch",
        hide_index=True,
        column_config={
            "Dicek (WIB)": st.column_config.TextColumn("Dicek (WIB)", width="medium"),
            "Nilai": st.column_config.TextColumn("Nilai", width="small"),
            "Nilai Numerik": st.column_config.TextColumn("Nilai Numerik", width="small"),
            "Perubahan": st.column_config.TextColumn("Perubahan", width="small"),
            "Status": st.column_config.TextColumn("Status", width="small"),
            "Device": st.column_config.TextColumn("Device", width="medium"),
            "Metrik": st.column_config.TextColumn("Metrik", width="medium"),
            "Catatan": st.column_config.TextColumn("Catatan", width="small"),
        },
    )

