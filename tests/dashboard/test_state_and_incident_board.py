from dashboard.components.incident_board import (
    LANE_IN_PROGRESS,
    LANE_RESOLVED,
    LANE_UNACKNOWLEDGED,
    parse_incident_query_id,
    partition_incidents,
)
from dashboard.components.state import clamp_page, sync_filter_page


def test_sync_filter_page_resets_only_when_signature_changes():
    state = {"page": 4, "signature": ("active", "site-a")}

    assert sync_filter_page(
        state,
        signature_key="signature",
        page_key="page",
        signature=("active", "site-a"),
    ) is False
    assert state["page"] == 4

    assert sync_filter_page(
        state,
        signature_key="signature",
        page_key="page",
        signature=("resolved", "site-a"),
    ) is True
    assert state["page"] == 1


def test_clamp_page_handles_invalid_and_out_of_range_values():
    assert clamp_page("invalid", 3) == 1
    assert clamp_page(9, 3) == 3
    assert clamp_page(-2, 3) == 1


def test_partition_incidents_builds_operational_lanes():
    lanes = partition_incidents(
        [
            {"id": 1, "status": "active", "acknowledged_at": None},
            {"id": 2, "status": "active", "acknowledged_at": "2026-06-20T09:00:00"},
            {"id": 3, "status": "resolved", "acknowledged_at": None},
        ]
    )

    assert [row["id"] for row in lanes[LANE_UNACKNOWLEDGED]] == [1]
    assert [row["id"] for row in lanes[LANE_IN_PROGRESS]] == [2]
    assert [row["id"] for row in lanes[LANE_RESOLVED]] == [3]


def test_parse_incident_query_id_accepts_positive_ids_only():
    assert parse_incident_query_id("42") == 42
    assert parse_incident_query_id(["7"]) == 7
    assert parse_incident_query_id("0") is None
    assert parse_incident_query_id("bad") is None
