"""Define test module behavior for `tests/services/test_observability_service.py`.

This module contains automated regression and validation scenarios.
"""

from datetime import timedelta

from backend.app.core.time import utcnow
from backend.app.models.scheduler_job_status import SchedulerJobStatus
from backend.app.services import observability_service as observability_module


def test_redact_sensitive_log_message_masks_telegram_credentials(monkeypatch):
    """Validate Telegram credentials are masked before log output."""
    monkeypatch.setattr(observability_module.settings, "telegram_bot_token", "123456:secret-token")
    monkeypatch.setattr(observability_module.settings, "telegram_chat_id", "-987654321")

    message = (
        "HTTP Request: POST https://api.telegram.org/bot123456:secret-token/sendMessage "
        'chat_id=-987654321 "HTTP/1.1 200 OK"'
    )

    redacted_message = observability_module.redact_sensitive_log_message(message)

    assert "123456:secret-token" not in redacted_message
    assert "-987654321" not in redacted_message
    assert "[telegram_bot_token]" in redacted_message
    assert "[telegram_chat_id]" in redacted_message


def test_scheduler_registration_heartbeat_prevents_stale_alert(monkeypatch):
    monkeypatch.setattr(observability_module.settings, "scheduler_cleanup_interval_hours", 24)
    old_timestamp = utcnow() - timedelta(days=4)
    status = SchedulerJobStatus(
        job_name="retention_cleanup",
        last_finished_at=old_timestamp,
        last_succeeded_at=old_timestamp,
        updated_at=utcnow(),
        consecutive_failures=0,
        is_running=False,
    )

    assert observability_module.scheduler_job_is_stale(status) is False


def test_scheduler_health_row_calculates_lag_and_stale_state(monkeypatch):
    reference_now = utcnow()
    monkeypatch.setattr(observability_module, "utcnow", lambda: reference_now)
    monkeypatch.setattr(observability_module.settings, "scheduler_interval_device_seconds", 60)
    monkeypatch.setattr(observability_module.settings, "scheduler_job_stale_factor", 3)
    status = SchedulerJobStatus(
        job_name="device_checks",
        last_finished_at=reference_now - timedelta(seconds=90),
        updated_at=reference_now - timedelta(seconds=90),
        consecutive_failures=0,
        is_running=False,
    )

    row = observability_module.build_scheduler_job_health_rows([status])[0]

    assert row["state"] == "on_schedule"
    assert row["expected_interval_seconds"] == 60
    assert row["schedule_lag_seconds"] == 30


def test_scheduler_health_row_marks_stale_after_configured_factor(monkeypatch):
    reference_now = utcnow()
    monkeypatch.setattr(observability_module, "utcnow", lambda: reference_now)
    monkeypatch.setattr(observability_module.settings, "scheduler_interval_device_seconds", 60)
    monkeypatch.setattr(observability_module.settings, "scheduler_job_stale_factor", 3)
    status = SchedulerJobStatus(
        job_name="device_checks",
        last_finished_at=reference_now - timedelta(seconds=181),
        updated_at=reference_now - timedelta(seconds=181),
        consecutive_failures=0,
        is_running=False,
    )

    assert observability_module.build_scheduler_job_health_rows([status])[0]["state"] == "stale"


def test_observability_payload_metrics_cover_paged_endpoints():
    original_payload_request_count = observability_module._api_payload_request_count.copy()
    original_payload_rows = observability_module._api_payload_rows.copy()
    original_payload_total_rows = observability_module._api_payload_total_rows.copy()
    original_payload_sampled = observability_module._api_payload_sampled.copy()

    observability_module._api_payload_request_count.clear()
    observability_module._api_payload_rows.clear()
    observability_module._api_payload_total_rows.clear()
    observability_module._api_payload_sampled.clear()

    try:
        observability_module.record_api_payload_request(endpoint="/devices/paged", scope="filtered")
        observability_module.record_api_payload_section(
            endpoint="/devices/paged",
            scope="filtered",
            section="items",
            rows=25,
            total_rows=120,
            sampled=True,
        )
        observability_module.record_api_payload_request(endpoint="/alerts/active/paged", scope="active")
        observability_module.record_api_payload_section(
            endpoint="/alerts/active/paged",
            scope="active",
            section="items",
            rows=20,
            total_rows=20,
            sampled=False,
        )
        observability_module.record_api_payload_request(endpoint="/incidents/paged", scope="active")
        observability_module.record_api_payload_section(
            endpoint="/incidents/paged",
            scope="active",
            section="items",
            rows=10,
            total_rows=30,
            sampled=True,
        )
        observability_module.record_api_payload_request(endpoint="/metrics/latest-snapshot/paged", scope="global")
        observability_module.record_api_payload_section(
            endpoint="/metrics/latest-snapshot/paged",
            scope="global",
            section="items",
            rows=100,
            total_rows=640,
            sampled=True,
        )

        metrics_text = observability_module.render_prometheus_metrics(
            database_up=True,
            scheduler_alert_count=0,
            scheduler_statuses=[],
        )

        assert (
            'network_monitoring_api_payload_requests_total{endpoint="/devices/paged",scope="filtered"} 1'
            in metrics_text
        )
        assert (
            "network_monitoring_api_payload_rows_total"
            '{endpoint="/alerts/active/paged",scope="active",section="items"} 20' in metrics_text
        )
        assert (
            "network_monitoring_api_payload_total_rows_sum"
            '{endpoint="/incidents/paged",scope="active",section="items"} 30' in metrics_text
        )
        assert (
            "network_monitoring_api_payload_sampled_total"
            '{endpoint="/metrics/latest-snapshot/paged",scope="global",section="items"} 1' in metrics_text
        )
    finally:
        observability_module._api_payload_request_count.clear()
        observability_module._api_payload_request_count.update(original_payload_request_count)
        observability_module._api_payload_rows.clear()
        observability_module._api_payload_rows.update(original_payload_rows)
        observability_module._api_payload_total_rows.clear()
        observability_module._api_payload_total_rows.update(original_payload_total_rows)
        observability_module._api_payload_sampled.clear()
        observability_module._api_payload_sampled.update(original_payload_sampled)


def test_agent_success_and_registration_do_not_clear_other_agent_failure(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tests.test_utils import create_all, drop_all, run

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    run(create_all(engine))

    async def scenario():
        async with sessions() as db:
            monkeypatch.setattr(observability_module.settings, "collector_agent_site", "Branch A")
            monkeypatch.setattr(observability_module.settings, "scheduler_interval_device_seconds", 30)
            await observability_module.mark_scheduler_job_failed(
                db, job_name="device_checks", duration_ms=1, error="site A failed"
            )
            monkeypatch.setattr(observability_module.settings, "collector_agent_site", "Branch B")
            monkeypatch.setattr(observability_module.settings, "scheduler_interval_device_seconds", 300)
            await observability_module.mark_scheduler_jobs_registered(db, job_names=["device_checks"])
            await observability_module.mark_scheduler_job_succeeded(db, job_name="device_checks", duration_ms=2)
            monkeypatch.setattr(observability_module.settings, "collector_agent_site", "")
            await observability_module.mark_scheduler_job_succeeded(db, job_name="device_checks", duration_ms=3)
            rows = await observability_module.list_scheduler_job_statuses(db)
            assert len(rows) == 3
            by_site = {row.agent_site: row for row in rows}
            assert by_site["Branch A"].consecutive_failures == 1
            assert by_site["Branch A"].last_error == "site A failed"
            assert by_site["Branch B"].consecutive_failures == 0
            assert by_site[None].agent_id == "central"
            assert by_site["Branch A"].expected_interval_seconds == 30
            assert by_site["Branch B"].expected_interval_seconds == 300
            # Another owner cannot refresh a stopped agent's heartbeat.
            stopped = by_site["Branch B"]
            stopped_at = utcnow() - timedelta(hours=1)
            stopped.last_finished_at = stopped_at
            stopped.updated_at = stopped_at
            health = {row["agent_site"]: row for row in observability_module.build_scheduler_job_health_rows(rows)}
            assert health["Branch B"]["state"] == "stale"
            assert health["Branch B"]["expected_interval_seconds"] == 300
            assert health[None]["state"] == "on_schedule"
            alerts = observability_module.build_scheduler_operational_alerts(rows)
            assert {row["agent_site"] for row in alerts} == {"Branch A", "Branch B"}
            metrics = observability_module.render_prometheus_metrics(
                database_up=True, scheduler_alert_count=2, scheduler_statuses=rows
            )
            from prometheus_client.parser import text_string_to_metric_families

            samples = [
                sample
                for family in text_string_to_metric_families(metrics)
                for sample in family.samples
                if sample.name == "network_monitoring_scheduler_job_consecutive_failures"
            ]
            assert len(samples) == 3
            assert len({sample.labels["agent_id"] for sample in samples}) == 3

    try:
        run(scenario())
    finally:
        run(drop_all(engine))
