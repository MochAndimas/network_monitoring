"""Clock-bound policy decisions without database, sender, or mutable settings."""

from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.app.alerting.engine_parts.notification_policy import (
    TelegramNotificationPolicy,
    _pending_active_telegram_events,
    _should_send_telegram_resolved_alert,
)
from backend.app.models.alert import Alert

NOW = datetime(2026, 9, 8, 12)
POLICY = TelegramNotificationPolicy(
    realtime_severities={"critical"},
    realtime_alert_types={"device_down"},
    realtime_device_types={"switch", "voip"},
    non_realtime_device_down_summary_seconds=900,
    site_outage_min_devices=0,
    site_outage_window_seconds=300,
    site_outage_cooldown_seconds=3600,
    summary_severities={"warning"},
    summary_alert_types={"slow_http_response"},
    alert_grace_period_seconds=60,
    summary_interval_seconds=300,
    summary_repeat_window_seconds=900,
    summary_repeat_min_count=3,
    flap_suppression_seconds=120,
    flap_repeat_window_seconds=900,
    flap_repeat_min_count=3,
    critical_reminder_interval_seconds=3600,
    voip_alert_grace_period_seconds=300,
    voip_critical_reminder_interval_seconds=28800,
    notification_cooldown_seconds=1800,
    resolved_correlation_window_seconds=900,
)


def select_events(alert, *, device_type="switch", current_time=NOW, policy=POLICY, **kwargs):
    return _pending_active_telegram_events(
        [alert],
        device_by_id={1: SimpleNamespace(id=1, device_type=device_type, site="Fixture")},
        device_type_by_id={1: device_type},
        policy=policy,
        current_time=current_time,
        **kwargs,
    )


def active_alert(*, age=120, notified_at=None):
    return Alert(
        id=1,
        device_id=1,
        alert_type="device_down",
        severity="critical",
        message="Fixture down",
        status="active",
        created_at=NOW - timedelta(seconds=age),
        telegram_notified_at=notified_at,
    )


@pytest.mark.parametrize("device_type,age", [("switch", 120), ("voip", 300)])
def test_active_eligibility_at_exact_grace_and_flap_boundary(device_type, age):
    alert = active_alert(age=age)
    assert select_events(alert, device_type=device_type, current_time=NOW - timedelta(microseconds=1)) == []
    events = select_events(alert, device_type=device_type)
    assert [event["action"] for event in events] == ["active"]
    assert alert.telegram_notified_at is None


@pytest.mark.parametrize("device_type,interval", [("switch", 3600), ("voip", 28800)])
def test_reminder_waits_for_its_device_specific_interval(device_type, interval):
    alert = active_alert(age=interval + 300, notified_at=NOW - timedelta(seconds=interval))
    assert select_events(alert, device_type=device_type, current_time=NOW - timedelta(microseconds=1)) == []
    assert [e["action"] for e in select_events(alert, device_type=device_type)] == ["active_reminder"]


def test_repeated_flap_still_respects_grace_and_replacement_cooldown():
    alert = active_alert(age=60)
    repeats = {(1, "device_down"): 3}
    assert select_events(alert) == []
    assert len(select_events(alert, recent_alert_counts=repeats)) == 1
    assert select_events(alert, current_time=NOW - timedelta(microseconds=1), recent_alert_counts=repeats) == []
    assert select_events(alert, recent_alert_counts=repeats, recently_notified_keys={(1, "device_down")}) == []


def test_non_realtime_device_uses_summary_window():
    alert = active_alert(age=900)
    assert select_events(alert, device_type="printer", current_time=NOW - timedelta(microseconds=1)) == []
    assert [e["action"] for e in select_events(alert, device_type="printer")] == ["summary_active"]


def test_explicit_policy_changes_do_not_leak_into_next_evaluation():
    alert = active_alert(age=120)
    slower_policy = replace(POLICY, alert_grace_period_seconds=500)
    assert select_events(alert, policy=slower_policy) == []
    assert len(select_events(alert)) == 1


def test_enqueue_without_ack_does_not_qualify_for_resolved_notification():
    alert = active_alert()
    assert not _should_send_telegram_resolved_alert(alert, NOW, "switch")
    alert.telegram_notified_at = NOW - timedelta(seconds=1)
    assert _should_send_telegram_resolved_alert(alert, NOW, "switch")
