"""Metric read cursors: focused metric/alert workflow responsibilities."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from fastapi import status as http_status

from ..api.pagination import decode_page_cursor, encode_page_cursor


def _metric_history_next_cursor(metrics: list[dict]) -> str | None:
    """Build a cursor from the last row in a metric-history page."""
    if not metrics:
        return None
    last_metric = metrics[-1]
    checked_at = last_metric["checked_at"]
    checked_at_value = checked_at.isoformat() if hasattr(checked_at, "isoformat") else str(checked_at)
    return encode_page_cursor({"checked_at": checked_at_value, "id": int(last_metric["id"])})


def _decode_metric_history_cursor(cursor: str) -> tuple[datetime, int]:
    """Decode a metric-history keyset cursor from the public API token."""
    payload = decode_page_cursor(cursor, detail="Invalid metrics history cursor")
    try:
        checked_at = datetime.fromisoformat(str(payload["checked_at"]))
        metric_id = int(payload["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail="Invalid metrics history cursor"
        ) from exc
    return checked_at, metric_id


def _latest_snapshot_next_cursor(metrics: list[dict]) -> str | None:
    """Build a cursor from the last row in a latest-snapshot page."""
    if not metrics:
        return None
    last_metric = metrics[-1]
    return encode_page_cursor(
        {
            "device_type_priority": int(last_metric["_sort_device_type_priority"]),
            "internet_target_name_priority": int(last_metric["_sort_internet_target_name_priority"]),
            "device_name": str(last_metric["_sort_device_name"]),
            "metric_name": str(last_metric["_sort_metric_name"]),
            "id": int(last_metric["id"]),
        }
    )


def _decode_latest_snapshot_cursor(cursor: str) -> dict:
    """Decode the latest-snapshot cursor used by keyset pagination."""
    payload = decode_page_cursor(cursor, detail="Invalid latest snapshot cursor")
    try:
        return {
            "device_type_priority": int(payload["device_type_priority"]),
            "internet_target_name_priority": int(payload["internet_target_name_priority"]),
            "device_name": str(payload["device_name"]),
            "metric_name": str(payload["metric_name"]),
            "id": int(payload["id"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail="Invalid latest snapshot cursor"
        ) from exc
