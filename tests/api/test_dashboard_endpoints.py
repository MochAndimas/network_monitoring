from contextlib import contextmanager
import asyncio
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.alert import Alert
from backend.app.repositories.device_repository import DeviceRepository
from backend.app.repositories.metric_repository import MetricRepository
from backend.app.services.monitoring_service import utcnow


TEST_API_KEY = "test-internal-key"
API_HEADERS = {"x-api-key": TEST_API_KEY}


def run(coro):
    return asyncio.run(coro)


class DummyScheduler:
    def start(self) -> None:
        return None

    def shutdown(self, wait: bool = False) -> None:
        return None


@contextmanager
def client_context():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = async_sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    run(_create_all(engine))

    async def override_get_db():
        async with TestingSessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db

    import backend.app.main as main_module
    import backend.app.api.deps as deps_module

    original_init_db = main_module.init_db
    original_scheduler_enabled = main_module.settings.scheduler_enabled
    original_create_scheduler = main_module.create_scheduler
    original_main_api_key = main_module.settings.internal_api_key
    original_deps_api_key = deps_module.settings.internal_api_key

    async def fake_init_db():
        return None

    main_module.init_db = fake_init_db
    main_module.settings.scheduler_enabled = False
    main_module.create_scheduler = lambda: DummyScheduler()
    main_module.settings.internal_api_key = TEST_API_KEY
    deps_module.settings.internal_api_key = TEST_API_KEY

    try:
        with TestClient(app) as client:
            yield client, TestingSessionLocal
    finally:
        main_module.init_db = original_init_db
        main_module.settings.scheduler_enabled = original_scheduler_enabled
        main_module.create_scheduler = original_create_scheduler
        main_module.settings.internal_api_key = original_main_api_key
        deps_module.settings.internal_api_key = original_deps_api_key
        app.dependency_overrides.clear()
        run(_drop_all(engine))


async def _create_all(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def _drop_all(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _seed_devices_and_metrics(session_factory, devices_payload: list[dict], metrics_payload: list[dict]):
    async with session_factory() as db:
        devices = await DeviceRepository(db).upsert_devices(devices_payload)
        if metrics_payload:
            await MetricRepository(db).create_metrics(metrics_payload(devices) if callable(metrics_payload) else metrics_payload)
        return devices


def test_devices_endpoint_returns_latest_status():
    with client_context() as (client, session_factory):
        run(
            _seed_devices_and_metrics(
                session_factory,
                [
                    {"name": "Google DNS", "ip_address": "8.8.8.8", "device_type": "internet_target"},
                    {"name": "Printer Finance", "ip_address": "192.168.1.50", "device_type": "printer"},
                ],
                lambda devices: [
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
                ],
            )
        )

        response = client.get("/devices")

        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 2
        assert {item["latest_status"] for item in payload} == {"up", "down"}


def test_dashboard_summary_and_alerts_endpoint():
    with client_context() as (client, session_factory):
        async def scenario():
            async with session_factory() as db:
                devices = await DeviceRepository(db).upsert_devices(
                    [
                        {"name": "Gateway Lokal", "ip_address": "192.168.1.1", "device_type": "internet_target"},
                        {"name": "Mikrotik Utama", "ip_address": "192.168.1.254", "device_type": "mikrotik"},
                        {"name": "Server Monitoring", "ip_address": "192.168.1.10", "device_type": "server"},
                    ]
                )
                await MetricRepository(db).create_metrics(
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
                await db.commit()

        run(scenario())

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
            headers=API_HEADERS,
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
            headers=API_HEADERS,
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
            headers=API_HEADERS,
            json={"name": "Broken Device", "ip_address": "not-an-ip", "device_type": "switch"},
        )
        invalid_type_response = client.post(
            "/devices",
            headers=API_HEADERS,
            json={"name": "Broken Device", "ip_address": "192.168.1.91", "device_type": "unknown_type"},
        )

        assert types_response.status_code == 200
        types_payload = types_response.json()
        assert any(item["value"] == "internet_target" for item in types_payload)

        assert invalid_ip_response.status_code == 422
        assert invalid_type_response.status_code == 422


def test_metrics_history_filters():
    with client_context() as (client, session_factory):
        async def scenario():
            async with session_factory() as db:
                devices = await DeviceRepository(db).upsert_devices(
                    [
                        {"name": "Server Monitoring", "ip_address": "192.168.1.10", "device_type": "server"},
                        {"name": "Mikrotik Utama", "ip_address": "192.168.1.254", "device_type": "mikrotik"},
                    ]
                )
                await MetricRepository(db).create_metrics(
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
                return devices[0].id

        server_device_id = run(scenario())

        response = client.get(f"/metrics/history?device_id={server_device_id}&metric_name=cpu_percent&status=warning")
        names_response = client.get(f"/metrics/names?device_id={server_device_id}")

        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 1
        assert payload[0]["metric_name"] == "cpu_percent"
        assert payload[0]["metric_value_numeric"] == 95.5
        assert names_response.status_code == 200
        assert names_response.json() == ["cpu_percent", "memory_percent"]


def test_devices_endpoint_supports_filters_and_pagination():
    with client_context() as (client, session_factory):
        run(
            _seed_devices_and_metrics(
                session_factory,
                [
                    {"name": "AP Lobby", "ip_address": "192.168.1.40", "device_type": "access_point"},
                    {"name": "Switch Core", "ip_address": "192.168.1.30", "device_type": "switch"},
                    {"name": "Printer Finance", "ip_address": "192.168.1.50", "device_type": "printer", "is_active": False},
                ],
                lambda devices: [
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
                        "metric_value": "2.10",
                        "status": "up",
                        "unit": "ms",
                        "checked_at": utcnow(),
                    },
                ],
            )
        )

        filtered_response = client.get("/devices?active_only=true&device_type=access_point&latest_status=down&search=Lobby")
        paged_response = client.get("/devices?limit=1&offset=1")

        assert filtered_response.status_code == 200
        filtered_payload = filtered_response.json()
        assert len(filtered_payload) == 1
        assert filtered_payload[0]["name"] == "AP Lobby"

        assert paged_response.status_code == 200
        assert len(paged_response.json()) == 1

        paged_meta_response = client.get("/devices/paged?active_only=true&limit=1&offset=0")
        assert paged_meta_response.status_code == 200
        paged_payload = paged_meta_response.json()
        assert paged_payload["meta"]["total"] == 2
        assert paged_payload["meta"]["limit"] == 1
        assert len(paged_payload["items"]) == 1


def test_metrics_history_supports_time_window_filters():
    with client_context() as (client, session_factory):
        async def scenario():
            async with session_factory() as db:
                devices = await DeviceRepository(db).upsert_devices(
                    [{"name": "Server Monitoring", "ip_address": "192.168.1.10", "device_type": "server"}]
                )
                now = utcnow()
                await MetricRepository(db).create_metrics(
                    [
                        {
                            "device_id": devices[0].id,
                            "metric_name": "cpu_percent",
                            "metric_value": "10.00",
                            "status": "ok",
                            "unit": "%",
                            "checked_at": now - timedelta(hours=2),
                        },
                        {
                            "device_id": devices[0].id,
                            "metric_name": "cpu_percent",
                            "metric_value": "35.00",
                            "status": "warning",
                            "unit": "%",
                            "checked_at": now - timedelta(minutes=20),
                        },
                    ]
                )
                return now

        now = run(scenario())
        checked_from = (now - timedelta(hours=1)).isoformat()
        checked_to = now.isoformat()

        response = client.get(f"/metrics/history?metric_name=cpu_percent&checked_from={checked_from}&checked_to={checked_to}")

        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 1
        assert payload[0]["metric_value"] == "35.00"

        paged_response = client.get(
            f"/metrics/history/paged?metric_name=cpu_percent&checked_from={checked_from}&checked_to={checked_to}&limit=10&offset=0"
        )
        assert paged_response.status_code == 200
        paged_payload = paged_response.json()
        assert paged_payload["meta"]["total"] == 1
        assert len(paged_payload["items"]) == 1


def test_run_cycle_creates_alerts_and_incidents():
    with client_context() as (client, session_factory):
        internet_device_id = run(
            _seed_devices_and_metrics(
                session_factory,
                [
                    {"name": "Google DNS", "ip_address": "8.8.8.8", "device_type": "internet_target"},
                    {"name": "Server Monitoring", "ip_address": "192.168.1.10", "device_type": "server"},
                ],
                [],
            )
        )[0].id

        import backend.app.services.run_cycle_service as run_cycle_module

        original_internet = run_cycle_module.run_internet_checks
        original_device = run_cycle_module.run_device_checks
        original_server = run_cycle_module.run_server_checks
        original_mikrotik = run_cycle_module.run_mikrotik_checks

        async def fake_internet_checks(_db):
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
            async def empty_checks(_db):
                return []

            run_cycle_module.run_device_checks = empty_checks
            run_cycle_module.run_server_checks = empty_checks
            run_cycle_module.run_mikrotik_checks = empty_checks

            cycle_response = client.post("/system/run-cycle", headers=API_HEADERS)
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

        update_response = client.put("/thresholds/cpu_warning", headers=API_HEADERS, json={"value": 92})
        assert update_response.status_code == 200
        assert update_response.json()["value"] == 92

        list_response_after = client.get("/thresholds")
        cpu_threshold = next(item for item in list_response_after.json() if item["key"] == "cpu_warning")
        assert cpu_threshold["value"] == 92


def test_run_cycle_creates_ping_latency_alert():
    with client_context() as (client, session_factory):
        internet_device_id = run(
            _seed_devices_and_metrics(
                session_factory,
                [{"name": "MyRepublic", "ip_address": "8.8.8.8", "device_type": "internet_target"}],
                [],
            )
        )[0].id

        import backend.app.services.run_cycle_service as run_cycle_module

        original_internet = run_cycle_module.run_internet_checks
        original_device = run_cycle_module.run_device_checks
        original_server = run_cycle_module.run_server_checks
        original_mikrotik = run_cycle_module.run_mikrotik_checks

        async def fake_internet_checks(_db):
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
            async def empty_checks(_db):
                return []

            run_cycle_module.run_device_checks = empty_checks
            run_cycle_module.run_server_checks = empty_checks
            run_cycle_module.run_mikrotik_checks = empty_checks

            cycle_response = client.post("/system/run-cycle", headers=API_HEADERS)
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
        internet_device_id = run(
            _seed_devices_and_metrics(
                session_factory,
                [{"name": "MyRepublic", "ip_address": "8.8.8.8", "device_type": "internet_target"}],
                [],
            )
        )[0].id

        import backend.app.services.run_cycle_service as run_cycle_module

        original_internet = run_cycle_module.run_internet_checks
        original_device = run_cycle_module.run_device_checks
        original_server = run_cycle_module.run_server_checks
        original_mikrotik = run_cycle_module.run_mikrotik_checks

        async def fake_internet_checks(_db):
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
            async def empty_checks(_db):
                return []

            run_cycle_module.run_device_checks = empty_checks
            run_cycle_module.run_server_checks = empty_checks
            run_cycle_module.run_mikrotik_checks = empty_checks

            cycle_response = client.post("/system/run-cycle", headers=API_HEADERS)
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
    with client_context() as (client, _session_factory):
        unauthorized_device = client.post(
            "/devices",
            json={"name": "Secured Device", "ip_address": "192.168.1.90", "device_type": "switch"},
        )
        unauthorized_cycle = client.post("/system/run-cycle")
        authorized_device = client.post(
            "/devices",
            headers=API_HEADERS,
            json={"name": "Secured Device", "ip_address": "192.168.1.90", "device_type": "switch"},
        )

        assert unauthorized_device.status_code == 401
        assert unauthorized_cycle.status_code == 401
        assert authorized_device.status_code == 201


def test_production_requires_internal_api_key():
    import backend.app.api.deps as deps_module

    with client_context() as (client, _session_factory):
        original_api_key = deps_module.settings.internal_api_key
        original_app_env = deps_module.settings.app_env
        deps_module.settings.internal_api_key = ""
        deps_module.settings.app_env = "production"

        try:
            response = client.post(
                "/devices",
                json={"name": "Missing Key", "ip_address": "192.168.1.91", "device_type": "switch"},
            )
        finally:
            deps_module.settings.internal_api_key = original_api_key
            deps_module.settings.app_env = original_app_env

        assert response.status_code == 503
        assert response.json()["detail"] == "INTERNAL_API_KEY is required in production"


def test_health_endpoint_and_request_id_header():
    import backend.app.api.routes.health as health_module

    original_check = health_module.check_database_connection
    async def fake_check_database_connection():
        return True

    health_module.check_database_connection = fake_check_database_connection

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

            response = client.get("/observability/summary")

        assert response.status_code == 200
        payload = response.json()
        assert payload["database"] == "up"
        assert payload["devices_total"] == 1
        assert payload["metrics_latest_snapshot"] >= 1
        assert payload["alerts_active"] == 1
    finally:
        observability_module.check_database_connection = original_check
