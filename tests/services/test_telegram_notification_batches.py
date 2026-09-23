"""Message bounds preserve Unicode text and exact alert acknowledgement ownership."""

from types import SimpleNamespace

import pytest

from backend.app.services.telegram_notification_batches import split_telegram_events
from backend.app.alerting.engine_parts.notification_formatting import _build_telegram_message


def event(alert_id: int, message: str = "fixture") -> dict[str, object]:
    return dict(
        alert_id=alert_id,
        action="active",
        alert_type="device_down",
        severity="critical",
        message=message,
        device=SimpleNamespace(id=1, name="Fixture", site="fixture"),
    )


def test_utf16_boundary_keeps_complete_events_and_reference_coverage():
    events = [event(1, "😀" * 800), event(2, "😀" * 800), event(3, "😀" * 800)]
    batches = split_telegram_events(events)
    assert len(batches) == 2
    assert all(len(batch.message.encode("utf-16-le")) // 2 <= 4096 for batch in batches)
    assert [ref.alert_id for batch in batches for ref in batch.references] == [1, 2, 3]
    assert sum(batch.message.count("😀") for batch in batches) == 2400


def test_exact_rendered_limit_fits_and_one_unit_less_splits():
    events = [event(1), event(2)]
    units = len(_build_telegram_message(events).encode("utf-16-le")) // 2
    assert len(split_telegram_events(events, max_message_units=units)) == 1
    assert len(split_telegram_events(events, max_message_units=units - 1)) == 2


def test_reference_limit_splits_without_losing_group_members():
    events = [event(i) for i in range(1, 5)]
    batches = split_telegram_events(events, max_references=2)
    assert [[ref.alert_id for ref in b.references] for b in batches] == [[1, 2], [3, 4]]


def test_single_large_event_is_rejected_without_truncation():
    with pytest.raises(ValueError, match="Individual.*message limit"):
        split_telegram_events([event(1, "😀" * 4096)])


def test_multi_alert_event_is_never_split_across_acknowledgements():
    item = event(1)
    item["alerts"] = [SimpleNamespace(id=i) for i in range(1, 4)]
    with pytest.raises(ValueError, match="Individual.*reference limit"):
        split_telegram_events([item], max_references=2)


def test_overlapping_references_are_rejected():
    with pytest.raises(ValueError, match="Overlapping"):
        split_telegram_events([event(1), event(1)])


def test_empty_group_has_no_jobs():
    assert split_telegram_events([]) == []


@pytest.mark.parametrize("limits", [{"max_message_units": 0}, {"max_message_units": 4097}, {"max_references": 251}])
def test_invalid_batch_limits(limits):
    with pytest.raises(ValueError, match="Invalid"):
        split_telegram_events([], **limits)
