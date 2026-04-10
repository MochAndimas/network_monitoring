from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.alert import Alert
from backend.app.repositories.device_repository import DeviceRepository
from backend.app.repositories.metric_repository import MetricRepository
from backend.app.services.monitoring_service import utcnow


class DummyScheduler:
    def start(self) -> None:
        return None

    def shutdown(self, wait: bool = False) -> None:
        return None


@contextmanager
def client_context():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    import backend.app.main as main_module

    original_init_db = main_module.init_db
    original_scheduler_enabled = main_module.settings.scheduler_enabled
    original_create_scheduler = main_module.create_scheduler

    main_module.init_db = lambda: None
    main_module.settings.scheduler_enabled = False
    main_module.create_scheduler = lambda: DummyScheduler()

    try:
        with TestClient(app) as client:
            yield client, TestingSessionLocal
    finally:
        main_module.init_db = original_init_db
        main_module.settings.scheduler_enabled = original_scheduler_enabled
        main_module.create_scheduler = original_create_scheduler
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_devices_endpoint_returns_latest_status():
    with client_context() as (client, session_factory):
        with session_factory() as db:
            devices = DeviceRepository(db).upsert_devices(
                [
                    {"name": "Google DNS", "ip_address": "8.8.8.8", "device_type": "internet_target"},
                    {"name": "Printer Finance", "ip_address": "192.168.1.50", "device_type": "printer"},
                ]
            )
            MetricRepository(db).create_metrics(
                [
                    {
                        "device_id": devices[0].id,
                        "metric_name": "ping",
                        "metric_value": "32.10",
                        "status": "up",
                        "unit": "ms",
                        "checked_at": utcnow(),
                    },
                    {
                        "device_id": devices[1].id,
                        "metric_name": "ping",
                        "metric_value": "timeout",
                        "status": "down",
                        "unit": None,
                        "checked_at": utcnow(),
                    },
                ]
            )

        response = client.get("/devices")

        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 2
        assert {item["latest_status"] for item in payload} == {"up", "down"}


def test_dashboard_summary_and_alerts_endpoint():
    with client_context() as (client, session_factory):
        with session_factory() as db:
            devices = DeviceRepository(db).upsert_devices(
                [
                    {"name": "Gateway Lokal", "ip_address": "192.168.1.1", "device_type": "internet_target"},
                    {"name": "Mikrotik Utama", "ip_address": "192.168.1.254", "device_type": "mikrotik"},
                    {"name": "Server Monitoring", "ip_address": "192.168.1.10", "device_type": "server"},
                ]
            )
            MetricRepository(db).create_metrics(
                [
                    {
                        "device_id": devices[0].id,
                        "metric_name": "ping",
                        "metric_value": "timeout",
                        "status": "down",
                        "unit": None,
                        "checked_at": utcnow(),
                    },
                    {
                        "device_id": devices[1].id,
                        "metric_name": "ping",
                        "metric_value": "4.25",
                        "status": "up",
                        "unit": "ms",
                        "checked_at": utcnow(),
                    },
                    {
                        "device_id": devices[2].id,
                        "metric_name": "ping",
                        "metric_value": "1.11",
                        "status": "up",
                        "unit": "ms",
                        "checked_at": utcnow(),
                    },
                ]
            )
            db.add(
                Alert(
                    device_id=devices[0].id,
                    alert_type="internet_loss",
                    severity="critical",
                    message="Gateway Lokal is unreachable",
                    status="active",
                    created_at=utcnow(),
                )
            )
            db.commit()

        summary_response = client.get("/dashboard/summary")
        alerts_response = client.get("/alerts/active")
        history_response = client.get("/metrics/history?limit=10")

        assert summary_response.status_code == 200
        assert summary_response.json() == {
            "internet_status": "down",
            "mikrotik_status": "up",
            "server_status": "up",
            "active_alerts": 1,
        }

        assert alerts_response.status_code == 200
        assert alerts_response.json()[0]["alert_type"] == "internet_loss"

        assert history_response.status_code == 200
        assert len(history_response.json()) == 3


def test_create_and_update_device_endpoint():
    with client_context() as (client, _session_factory):
        create_response = client.post(
            "/devices",
            json={
                "name": "AP Lobby",
                "ip_address": "192.168.1.77",
                "device_type": "access_point",
                "site": "Main Office",
                "description": "Lobby access point",
                "is_active": True,
            },
        )

        assert create_response.status_code == 201
        created_payload = create_response.json()
        assert created_payload["name"] == "AP Lobby"
        assert created_payload["latest_status"] == "unknown"

        update_response = client.put(
            f'/devices/{created_payload["id"]}',
            json={
                "name": "AP Lobby Updated",
                "description": "Updated description",
                "is_active": False,
            },
        )

        assert update_response.status_code == 200
        updated_payload = update_response.json()
        assert updated_payload["name"] == "AP Lobby Updated"
        assert updated_payload["is_active"] is False


def test_device_type_metadata_and_validation():
    with client_context() as (client, _session_factory):
        types_response = client.get("/devices/meta/types")
        invalid_ip_response = client.post(
            "/devices",
            json={"name": "Broken Device", "ip_address": "not-an-ip", "device_type": "switch"},
        )
        invalid_type_response = client.post(
            "/devices",
            json={"name": "Broken Device", "ip_address": "192.168.1.91", "device_type": "unknown_type"},
        )

        assert types_response.status_code == 200
        types_payload = types_response.json()
        assert any(item["value"] == "internet_target" for item in types_payload)

        assert invalid_ip_response.status_code == 422
        assert invalid_type_response.status_code == 422


def test_metrics_history_filters():
    with client_context() as (client, session_factory):
        with session_factory() as db:
            devices = DeviceRepository(db).upsert_devices(
                [
                    {"name": "Server Monitoring", "ip_address": "192.168.1.10", "device_type": "server"},
                    {"name": "Mikrotik Utama", "ip_address": "192.168.1.254", "device_type": "mikrotik"},
                ]
            )
            MetricRepository(db).create_metrics(
                [
                    {
                        "device_id": devices[0].id,
                        "metric_name": "cpu_percent",
                        "metric_value": "95.50",
                        "status": "warning",
                        "unit": "%",
                        "checked_at": utcnow(),
                    },
                    {
                        "device_id": devices[0].id,
                        "metric_name": "memory_percent",
                        "metric_value": "70.25",
                        "status": "ok",
                        "unit": "%",
                        "checked_at": utcnow(),
                    },
                    {
                        "device_id": devices[1].id,
                        "metric_name": "cpu_percent",
                        "metric_value": "20.00",
                        "status": "ok",
                        "unit": "%",
                        "checked_at": utcnow(),
                    },
                ]
            )
            server_device_id = devices[0].id

        response = client.get(f"/metrics/history?device_id={server_device_id}&metric_name=cpu_percent&status=warning")
        names_response = client.get(f"/metrics/names?device_id={server_device_id}")

        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 1
        assert payload[0]["metric_name"] == "cpu_percent"
        assert payload[0]["metric_value_numeric"] == 95.5
        assert names_response.status_code == 200
        assert names_response.json() == ["cpu_percent", "memory_percent"]


def test_run_cycle_creates_alerts_and_incidents():
    with client_context() as (client, session_factory):
        with session_factory() as db:
            devices = DeviceRepository(db).upsert_devices(
                [
                    {"name": "Google DNS", "ip_address": "8.8.8.8", "device_type": "internet_target"},
                    {"name": "Server Monitoring", "ip_address": "192.168.1.10", "device_type": "server"},
                ]
            )
            internet_device_id = devices[0].id

        import backend.app.services.run_cycle_service as run_cycle_module

        original_internet = run_cycle_module.run_internet_checks
        original_device = run_cycle_module.run_device_checks
        original_server = run_cycle_module.run_server_checks
        original_mikrotik = run_cycle_module.run_mikrotik_checks

        def fake_internet_checks(_db):
            return [
                {
                    "device_id": internet_device_id,
                    "metric_name": "ping",
                    "metric_value": "timeout",
                    "status": "down",
                    "unit": None,
                    "checked_at": utcnow(),
                }
            ]

        try:
            run_cycle_module.run_internet_checks = fake_internet_checks
            run_cycle_module.run_device_checks = lambda _db: []
            run_cycle_module.run_server_checks = lambda _db: []
            run_cycle_module.run_mikrotik_checks = lambda _db: []

            cycle_response = client.post("/system/run-cycle")
            incidents_response = client.get("/incidents?status=active")
            alerts_response = client.get("/alerts/active")
        finally:
            run_cycle_module.run_internet_checks = original_internet
            run_cycle_module.run_device_checks = original_device
            run_cycle_module.run_server_checks = original_server
            run_cycle_module.run_mikrotik_checks = original_mikrotik

        assert cycle_response.status_code == 200
        cycle_payload = cycle_response.json()
        assert cycle_payload["metrics_collected"] == 1
        assert cycle_payload["alerts_created"] == 1
        assert cycle_payload["incidents_created"] == 1

        assert alerts_response.status_code == 200
        assert len(alerts_response.json()) == 1
        assert alerts_response.json()[0]["alert_type"] == "internet_loss"

        assert incidents_response.status_code == 200
        assert len(incidents_response.json()) == 1
        assert incidents_response.json()[0]["status"] == "active"


def test_threshold_endpoints_and_update():
    with client_context() as (client, _session_factory):
        list_response = client.get("/thresholds")

        assert list_response.status_code == 200
        payload = list_response.json()
        assert any(item["key"] == "cpu_warning" for item in payload)
        assert any(item["key"] == "ping_latency_warning" for item in payload)
        assert any(item["key"] == "ping_latency_critical" for item in payload)
        assert any(item["key"] == "packet_loss_warning" for item in payload)
        assert any(item["key"] == "packet_loss_critical" for item in payload)
        assert any(item["key"] == "jitter_warning" for item in payload)
        assert any(item["key"] == "jitter_critical" for item in payload)
        assert any(item["key"] == "dns_resolution_warning" for item in payload)
        assert any(item["key"] == "http_response_warning" for item in payload)

        update_response = client.put("/thresholds/cpu_warning", json={"value": 92})
        assert update_response.status_code == 200
        assert update_response.json()["value"] == 92

        list_response_after = client.get("/thresholds")
        cpu_threshold = next(item for item in list_response_after.json() if item["key"] == "cpu_warning")
        assert cpu_threshold["value"] == 92


def test_run_cycle_creates_ping_latency_alert():
    with client_context() as (client, session_factory):
        with session_factory() as db:
            devices = DeviceRepository(db).upsert_devices(
                [
                    {"name": "MyRepublic", "ip_address": "8.8.8.8", "device_type": "internet_target"},
                ]
            )
            internet_device_id = devices[0].id

        import backend.app.services.run_cycle_service as run_cycle_module

        original_internet = run_cycle_module.run_internet_checks
        original_device = run_cycle_module.run_device_checks
        original_server = run_cycle_module.run_server_checks
        original_mikrotik = run_cycle_module.run_mikrotik_checks

        def fake_internet_checks(_db):
            return [
                {
                    "device_id": internet_device_id,
                    "metric_name": "ping",
                    "metric_value": "205.00",
                    "status": "up",
                    "unit": "ms",
                    "checked_at": utcnow(),
                }
            ]

        try:
            run_cycle_module.run_internet_checks = fake_internet_checks
            run_cycle_module.run_device_checks = lambda _db: []
            run_cycle_module.run_server_checks = lambda _db: []
            run_cycle_module.run_mikrotik_checks = lambda _db: []

            cycle_response = client.post("/system/run-cycle")
            alerts_response = client.get("/alerts/active")
        finally:
            run_cycle_module.run_internet_checks = original_internet
            run_cycle_module.run_device_checks = original_device
            run_cycle_module.run_server_checks = original_server
            run_cycle_module.run_mikrotik_checks = original_mikrotik

        assert cycle_response.status_code == 200
        cycle_payload = cycle_response.json()
        assert cycle_payload["metrics_collected"] == 1
        assert cycle_payload["alerts_created"] == 1

        assert alerts_response.status_code == 200
        alerts_payload = alerts_response.json()
        assert len(alerts_payload) == 1
        assert alerts_payload[0]["alert_type"] == "high_ping_latency_critical"
        assert alerts_payload[0]["severity"] == "critical"


def test_run_cycle_creates_internet_quality_alerts():
    with client_context() as (client, session_factory):
        with session_factory() as db:
            devices = DeviceRepository(db).upsert_devices(
                [
                    {"name": "MyRepublic", "ip_address": "8.8.8.8", "device_type": "internet_target"},
                ]
            )
            internet_device_id = devices[0].id

        import backend.app.services.run_cycle_service as run_cycle_module

        original_internet = run_cycle_module.run_internet_checks
        original_device = run_cycle_module.run_device_checks
        original_server = run_cycle_module.run_server_checks
        original_mikrotik = run_cycle_module.run_mikrotik_checks

        def fake_internet_checks(_db):
            return [
                {
                    "device_id": internet_device_id,
                    "metric_name": "packet_loss",
                    "metric_value": "55.00",
                    "status": "warning",
                    "unit": "%",
                    "checked_at": utcnow(),
                },
                {
                    "device_id": internet_device_id,
                    "metric_name": "jitter",
                    "metric_value": "35.00",
                    "status": "warning",
                    "unit": "ms",
                    "checked_at": utcnow(),
                },
                {
                    "device_id": internet_device_id,
                    "metric_name": "dns_resolution_time",
                    "metric_value": "failed",
                    "status": "down",
                    "unit": None,
                    "checked_at": utcnow(),
                },
                {
                    "device_id": internet_device_id,
                    "metric_name": "http_response_time",
                    "metric_value": "1200.00",
                    "status": "up",
                    "unit": "ms",
                    "checked_at": utcnow(),
                },
                {
                    "device_id": internet_device_id,
                    "metric_name": "public_ip",
                    "metric_value": "203.0.113.20",
                    "status": "warning",
                    "unit": None,
                    "checked_at": utcnow(),
                },
            ]

        try:
            run_cycle_module.run_internet_checks = fake_internet_checks
            run_cycle_module.run_device_checks = lambda _db: []
            run_cycle_module.run_server_checks = lambda _db: []
            run_cycle_module.run_mikrotik_checks = lambda _db: []

            cycle_response = client.post("/system/run-cycle")
            alerts_response = client.get("/alerts/active")
        finally:
            run_cycle_module.run_internet_checks = original_internet
            run_cycle_module.run_device_checks = original_device
            run_cycle_module.run_server_checks = original_server
            run_cycle_module.run_mikrotik_checks = original_mikrotik

        assert cycle_response.status_code == 200
        cycle_payload = cycle_response.json()
        assert cycle_payload["metrics_collected"] == 5
        assert cycle_payload["alerts_created"] == 5

        assert alerts_response.status_code == 200
        alert_types = {alert["alert_type"] for alert in alerts_response.json()}
        assert alert_types == {
            "high_packet_loss_critical",
            "high_jitter_warning",
            "dns_resolution_failed",
            "slow_http_response",
            "public_ip_changed",
        }


def test_internal_api_key_protects_mutation_endpoints():
    import backend.app.core.config as config_module
    import backend.app.api.deps as deps_module

    original_config_key = config_module.settings.internal_api_key
    original_deps_key = deps_module.settings.internal_api_key
    config_module.settings.internal_api_key = "secret-key"
    deps_module.settings.internal_api_key = "secret-key"

    try:
        with client_context() as (client, _session_factory):
            unauthorized_device = client.post(
                "/devices",
                json={"name": "Secured Device", "ip_address": "192.168.1.90", "device_type": "switch"},
            )
            unauthorized_cycle = client.post("/system/run-cycle")
            authorized_device = client.post(
                "/devices",
                headers={"x-api-key": "secret-key"},
                json={"name": "Secured Device", "ip_address": "192.168.1.90", "device_type": "switch"},
            )

            assert unauthorized_device.status_code == 401
            assert unauthorized_cycle.status_code == 401
            assert authorized_device.status_code == 201
    finally:
        config_module.settings.internal_api_key = original_config_key
        deps_module.settings.internal_api_key = original_deps_key


def test_health_endpoint_and_request_id_header():
    import backend.app.api.routes.health as health_module

    original_check = health_module.check_database_connection
    health_module.check_database_connection = lambda: True

    try:
        with client_context() as (client, _session_factory):
            response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "up"}
        assert "X-Request-ID" in response.headers
    finally:
        health_module.check_database_connection = original_check


def test_observability_summary_endpoint():
    import backend.app.api.routes.observability as observability_module

    original_check = observability_module.check_database_connection
    observability_module.check_database_connection = lambda: True

    try:
        with client_context() as (client, session_factory):
            with session_factory() as db:
                devices = DeviceRepository(db).upsert_devices(
                    [
                        {"name": "Google DNS", "ip_address": "8.8.8.8", "device_type": "internet_target"},
                    ]
                )
                MetricRepository(db).create_metrics(
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
                db.commit()

            response = client.get("/observability/summary")

        assert response.status_code == 200
        payload = response.json()
        assert payload["database"] == "up"
        assert payload["devices_total"] == 1
        assert payload["metrics_latest_snapshot"] >= 1
        assert payload["alerts_active"] == 1
    finally:
        observability_module.check_database_connection = original_check
