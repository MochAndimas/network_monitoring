"""Pure incident-board helpers shared by Streamlit views and tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


LANE_UNACKNOWLEDGED = "unacknowledged"
LANE_IN_PROGRESS = "in_progress"
LANE_RESOLVED = "resolved"
LANE_ORDER = (LANE_UNACKNOWLEDGED, LANE_IN_PROGRESS, LANE_RESOLVED)


def incident_lane(item: Mapping[str, object]) -> str:
    """Classify an incident into one operational board lane."""
    status = str(item.get("status") or "").strip().lower()
    if status == "resolved":
        return LANE_RESOLVED
    if item.get("acknowledged_at"):
        return LANE_IN_PROGRESS
    return LANE_UNACKNOWLEDGED


def partition_incidents(items: Iterable[Mapping[str, object]]) -> dict[str, list[dict[str, object]]]:
    """Partition incidents while preserving input order inside each lane."""
    lanes: dict[str, list[dict[str, object]]] = {lane: [] for lane in LANE_ORDER}
    for item in items:
        row = dict(item)
        lanes[incident_lane(row)].append(row)
    return lanes


def parse_incident_query_id(value: object) -> int | None:
    """Parse a positive incident id from Streamlit query parameters."""
    if isinstance(value, list):
        value = value[0] if value else None
    try:
        incident_id = int(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    return incident_id if incident_id > 0 else None
