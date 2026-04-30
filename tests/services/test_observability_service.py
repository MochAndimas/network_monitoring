"""Define test module behavior for `tests/services/test_observability_service.py`.

This module contains automated regression and validation scenarios.
"""

from backend.app.services import observability_service as observability_module


def test_redact_sensitive_log_message_masks_telegram_credentials(monkeypatch):
    """Validate Telegram credentials are masked before log output."""
    monkeypatch.setattr(observability_module.settings, "telegram_bot_token", "123456:secret-token")
    monkeypatch.setattr(observability_module.settings, "telegram_chat_id", "-987654321")

    message = (
        'HTTP Request: POST https://api.telegram.org/bot123456:secret-token/sendMessage '
        'chat_id=-987654321 "HTTP/1.1 200 OK"'
    )

    redacted_message = observability_module.redact_sensitive_log_message(message)

    assert "123456:secret-token" not in redacted_message
    assert "-987654321" not in redacted_message
    assert "[telegram_bot_token]" in redacted_message
    assert "[telegram_chat_id]" in redacted_message


def test_observability_payload_metrics_cover_paged_endpoints():
    """Validate that observability payload metrics cover paged endpoints.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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

        assert 'network_monitoring_api_payload_requests_total{endpoint="/devices/paged",scope="filtered"} 1' in metrics_text
        assert (
            'network_monitoring_api_payload_rows_total'
            '{endpoint="/alerts/active/paged",scope="active",section="items"} 20'
            in metrics_text
        )
        assert (
            'network_monitoring_api_payload_total_rows_sum'
            '{endpoint="/incidents/paged",scope="active",section="items"} 30'
            in metrics_text
        )
        assert (
            'network_monitoring_api_payload_sampled_total'
            '{endpoint="/metrics/latest-snapshot/paged",scope="global",section="items"} 1'
            in metrics_text
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
