from __future__ import annotations

import math
from typing import Iterable, Sequence

import streamlit as st


def render_page_header(title: str, description: str) -> None:
    st.title(title)
    st.caption(description)


def render_meta_row(items: Sequence[tuple[str, object]]) -> None:
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
    if not items:
        return
    columns_per_row = max(columns_per_row, 1)
    row_count = math.ceil(len(items) / columns_per_row)
    for row_index in range(row_count):
        row_items = items[row_index * columns_per_row : (row_index + 1) * columns_per_row]
        columns = st.columns(len(row_items))
        for column, (label, value, delta) in zip(columns, row_items, strict=False):
            with column.container(border=True):
                st.metric(label, value, delta=delta)


def normalize_status_label(value: object) -> str:
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


def count_if(values: Iterable[object], expected: set[str]) -> int:
    normalized_expected = {item.strip().lower() for item in expected}
    return sum(1 for value in values if str(value or "").strip().lower() in normalized_expected)
