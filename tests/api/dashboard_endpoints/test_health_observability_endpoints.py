"""Define test module behavior for `tests/api/dashboard_endpoints/test_health_observability_endpoints.py`.

This module contains automated regression and validation scenarios.
"""

from .common import (
    Alert,
    API_HEADERS,
    client_context,
    DeviceRepository,
    MetricRepository,
    run,
    SchedulerJobStatus,
    utcnow,
)

def test_health_endpoint_and_request_id_header():
    """Validate that health endpoint and request id header.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    import backend.app.api.routes.health as health_module

    original_check = health_module.check_database_connection
    async def fake_check_database_connection():
        return True

    health_module.check_database_connection = fake_check_database_connection

    try:
        with client_context() as (client, _session_factory):
            response = client.get("/health")
            live_response = client.get("/health/live")
            ready_response = client.get("/health/ready")
            dependencies_response = client.get("/health/dependencies")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "up", "scheduler": "up"}
        assert live_response.status_code == 200
        assert live_response.json() == {"status": "ok"}
        assert ready_response.status_code == 200
        assert ready_response.json()["status"] == "ready"
        assert dependencies_response.status_code == 200
        assert dependencies_response.json()["database"] == "up"
        assert "X-Request-ID" in response.headers
    finally:
        health_module.check_database_connection = original_check

def test_health_ready_stays_up_when_scheduler_is_degraded():
    """Validate that health ready stays up when scheduler is degraded.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    import backend.app.api.routes.health as health_module

    original_check = health_module.check_database_connection
    original_list_statuses = health_module.list_scheduler_job_statuses

    async def fake_check_database_connection():
        return True

    async def fake_list_scheduler_job_statuses(_db):
        return [
            SchedulerJobStatus(
                job_name="device_checks",
                consecutive_failures=2,
                is_running=False,
                last_error="router timeout",
            )
        ]

    health_module.check_database_connection = fake_check_database_connection
    health_module.list_scheduler_job_statuses = fake_list_scheduler_job_statuses

    try:
        with client_context() as (client, _session_factory):
            response = client.get("/health")
            ready_response = client.get("/health/ready")
            dependencies_response = client.get("/health/dependencies")

        assert response.status_code == 503
        assert response.json()["scheduler"] == "degraded"
        assert ready_response.status_code == 200
        assert ready_response.json()["status"] == "ready"
        assert ready_response.json()["dependencies"]["scheduler"] == "degraded"
        assert dependencies_response.status_code == 503
        assert dependencies_response.json()["scheduler_alerts"]
    finally:
        health_module.check_database_connection = original_check
        health_module.list_scheduler_job_statuses = original_list_statuses

def test_observability_metrics_use_route_templates_for_http_paths():
    """Validate that observability metrics use route templates for http paths.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    import backend.app.services.observability_service as observability_module

    original_request_count = observability_module._http_request_count.copy()
    original_request_duration = observability_module._http_request_duration_ms.copy()
    original_request_errors = observability_module._http_request_errors.copy()

    observability_module._http_request_count.clear()
    observability_module._http_request_duration_ms.clear()
    observability_module._http_request_errors.clear()

    try:
        observability_module.record_http_request(
            path="/devices/123",
            route_path="/devices/{device_id}",
            method="GET",
            status_code=200,
            duration_ms=12.5,
        )
        metrics = observability_module.render_prometheus_metrics(
            database_up=True,
            scheduler_alert_count=0,
            scheduler_statuses=[],
        )

        assert 'path="/devices/{device_id}"' in metrics
        assert 'path="/devices/123"' not in metrics
    finally:
        observability_module._http_request_count.clear()
        observability_module._http_request_count.update(original_request_count)
        observability_module._http_request_duration_ms.clear()
        observability_module._http_request_duration_ms.update(original_request_duration)
        observability_module._http_request_errors.clear()
        observability_module._http_request_errors.update(original_request_errors)

def test_observability_metrics_include_history_payload_counters():
    """Validate that observability metrics include history payload counters.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    import backend.app.services.observability_service as observability_module

    original_payload_request_count = observability_module._api_payload_request_count.copy()
    original_payload_rows = observability_module._api_payload_rows.copy()
    original_payload_total_rows = observability_module._api_payload_total_rows.copy()
    original_payload_sampled = observability_module._api_payload_sampled.copy()

    observability_module._api_payload_request_count.clear()
    observability_module._api_payload_rows.clear()
    observability_module._api_payload_total_rows.clear()
    observability_module._api_payload_sampled.clear()

    try:
        observability_module.record_api_payload_request(endpoint="/metrics/history/live", scope="global")
        observability_module.record_api_payload_section(
            endpoint="/metrics/history/live",
            scope="global",
            section="history",
            rows=120,
            total_rows=120,
            sampled=True,
        )
        observability_module.record_api_payload_section(
            endpoint="/metrics/history/live",
            scope="global",
            section="latest_snapshot",
            rows=10,
            total_rows=99,
            sampled=True,
        )
        metrics = observability_module.render_prometheus_metrics(
            database_up=True,
            scheduler_alert_count=0,
            scheduler_statuses=[],
        )
        assert (
            'network_monitoring_api_payload_requests_total{endpoint="/metrics/history/live",scope="global"} 1'
            in metrics
        )
        assert (
            'network_monitoring_api_payload_rows_total{endpoint="/metrics/history/live",scope="global",section="history"} 120'
            in metrics
        )
        assert (
            'network_monitoring_api_payload_total_rows_sum'
            '{endpoint="/metrics/history/live",scope="global",section="latest_snapshot"} 99'
            in metrics
        )
        assert (
            'network_monitoring_api_payload_sampled_total'
            '{endpoint="/metrics/history/live",scope="global",section="latest_snapshot"} 1'
            in metrics
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

def test_observability_summary_endpoint():
    """Validate that observability summary endpoint.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    import backend.app.api.routes.observability as observability_module

    original_check = observability_module.check_database_connection
    async def fake_check_database_connection():
        return True

    observability_module.check_database_connection = fake_check_database_connection

    try:
        with client_context() as (client, session_factory):
            async def scenario():
                async with session_factory() as db:
                    devices = await DeviceRepository(db).upsert_devices(
                        [
                            {"name": "Google DNS", "ip_address": "8.8.8.8", "device_type": "internet_target"},
                        ]
                    )
                    await MetricRepository(db).create_metrics(
                        [
                            {
                                "device_id": devices[0].id,
                                "metric_name": "ping",
                                "metric_value": "10.50",
                                "status": "up",
                                "unit": "ms",
                                "checked_at": utcnow(),
                            }
                        ]
                    )
                    db.add(
                        Alert(
                            device_id=devices[0].id,
                            alert_type="internet_loss",
                            severity="critical",
                            message="test",
                            status="active",
                            created_at=utcnow(),
                        )
                    )
                    await db.commit()

            run(scenario())

            response = client.get("/observability/summary", headers=API_HEADERS)
            metrics_response = client.get("/observability/metrics", headers=API_HEADERS)

        assert response.status_code == 200
        payload = response.json()
        assert payload["database"] == "up"
        assert payload["devices_total"] == 1
        assert payload["metrics_latest_snapshot"] >= 1
        assert payload["alerts_active"] == 1
        assert "auth" in payload
        assert "active_sessions" in payload["auth"]
        assert "login_failures_window" in payload["auth"]
        assert "scheduler_jobs" in payload
        assert "operational_alerts" in payload
        assert metrics_response.status_code == 200
        assert "network_monitoring_database_up 1" in metrics_response.text
    finally:
        observability_module.check_database_connection = original_check

