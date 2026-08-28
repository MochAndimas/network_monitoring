"""Streamlit dashboard helpers for ui."""

from __future__ import annotations

import math
from typing import Any, Sequence

import pandas as pd
import streamlit as st


def render_page_header(title: str, description: str) -> None:
    """Render page header for the dashboard UI."""
    st.title(title)
    st.caption(description)


def render_meta_row(items: Sequence[tuple[str, object]]) -> None:
    """Render meta row for the dashboard UI."""
    if not items:
        return
    with st.container(border=True):
        columns = st.columns(len(items))
        for column, (label, value) in zip(columns, items, strict=False):
            column.caption(label)
            column.write(str(value))


def render_kpi_cards(
    items: Sequence[tuple[str, object, str | None]],
    *,
    columns_per_row: int = 4,
) -> None:
    """Render kpi cards for the dashboard UI."""
    if not items:
        return
    columns_per_row = max(columns_per_row, 1)
    row_count = math.ceil(len(items) / columns_per_row)
    for row_index in range(row_count):
        row_items = items[row_index * columns_per_row : (row_index + 1) * columns_per_row]
        columns = st.columns(len(row_items))
        for column, (label, value, delta) in zip(columns, row_items, strict=False):
            with column.container(border=True):
                st.metric(label, str(value), delta=delta)


def dataframe_to_csv_bytes(dataframe: pd.DataFrame) -> bytes:
    """Return a UTF-8 CSV payload for dashboard downloads."""
    if dataframe.empty:
        return b""
    return dataframe.to_csv(index=False).encode("utf-8")


def render_csv_download(
    label: str,
    dataframe: pd.DataFrame,
    *,
    file_name: str,
    key: str,
) -> None:
    """Render a CSV download button for a non-empty dataframe."""
    if dataframe.empty:
        return
    st.download_button(
        label,
        data=dataframe_to_csv_bytes(dataframe),
        file_name=file_name,
        mime="text/csv",
        key=key,
    )


def render_section_header_with_download(
    title: str,
    dataframe: pd.DataFrame,
    *,
    file_name: str,
    key: str,
    level: int = 3,
) -> None:
    """Render a section title with a right-aligned CSV download button."""
    title_col, download_col = st.columns([4, 1])
    heading_level = "#" * max(min(int(level), 6), 1)
    title_col.markdown(f"{heading_level} {title}")
    with download_col:
        render_csv_download(
            "Download CSV",
            dataframe,
            file_name=file_name,
            key=key,
        )


def render_paginated_dataframe(
    dataframe: pd.DataFrame,
    *,
    key: str,
    label: str = "Tabel",
    page_size_options: Sequence[int] = (10, 25, 50, 100),
    default_page_size: int = 10,
    **dataframe_kwargs: Any,
) -> None:
    """Render a dataframe page with controls below it to avoid long scrolling tables."""
    normalized_options = tuple(sorted({max(int(option), 1) for option in page_size_options}))
    if not normalized_options:
        normalized_options = (10,)
    default_page_size = min(normalized_options, key=lambda option: abs(option - default_page_size))
    page_size_key = f"{key}_page_size"
    page_key = f"{key}_page"
    if page_size_key not in st.session_state:
        st.session_state[page_size_key] = default_page_size

    page_size = int(st.session_state[page_size_key])
    if len(dataframe) <= page_size:
        st.dataframe(dataframe, **dataframe_kwargs)
        return
    page_count = max(math.ceil(len(dataframe) / page_size), 1)
    current_page = int(st.session_state.get(page_key, 1))
    if current_page > page_count:
        st.session_state[page_key] = page_count
        current_page = page_count
    elif current_page < 1:
        st.session_state[page_key] = 1
        current_page = 1

    start = (current_page - 1) * page_size
    st.dataframe(dataframe.iloc[start : start + page_size], **dataframe_kwargs)

    control_col, page_col = st.columns([1, 1])
    control_col.selectbox(
        f"Baris {label}",
        options=normalized_options,
        key=page_size_key,
    )
    page_col.number_input(
        f"Halaman {label}",
        min_value=1,
        max_value=page_count,
        step=1,
        key=page_key,
    )
    if dataframe.empty:
        st.caption("Tidak ada baris untuk ditampilkan.")
    else:
        st.caption(f"Menampilkan {start + 1}-{min(start + page_size, len(dataframe))} dari {len(dataframe)} baris.")


def freshness_label(
    value,
    *,
    fresh_minutes: int = 5,
    stale_minutes: int = 15,
) -> str:
    """Return a compact freshness label from a timestamp-like value."""
    if value is None or pd.isna(value):
        return "No data"
    timestamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(timestamp):
        return "No data"
    age_minutes = (pd.Timestamp.utcnow() - timestamp).total_seconds() / 60
    if age_minutes <= fresh_minutes:
        state = "Fresh"
    elif age_minutes <= stale_minutes:
        state = "Aging"
    else:
        state = "Stale"
    return f"{state} ({age_minutes:.0f}m ago)"


def normalize_status_label(value: object) -> str:
    """Normalize status label for the dashboard UI."""
    normalized = str(value or "").strip().lower()
    if not normalized:
        return "Unknown"
    labels = {
        "up": "Up",
        "ok": "OK",
        "warning": "Warning",
        "down": "Down",
        "error": "Error",
        "unknown": "Unknown",
        "active": "Active",
        "resolved": "Resolved",
    }
    return labels.get(normalized, normalized.replace("_", " ").title())


def status_priority(value: object) -> int:
    """Return status priority used by the dashboard UI."""
    normalized = str(value or "").strip().lower()
    priorities = {
        "critical": 0,
        "high": 1,
        "error": 2,
        "down": 3,
        "warning": 4,
        "active": 5,
        "unknown": 6,
        "resolved": 7,
        "ok": 8,
        "up": 9,
    }
    return priorities.get(normalized, 99)
