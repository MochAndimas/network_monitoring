from contextlib import contextmanager
import asyncio
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.scheduler_job_status import SchedulerJobStatus
from backend.app.models.alert import Alert
from backend.app.models.user import AuthSession
from backend.app.models.user import User
from backend.app.core.security import AuthConfigurationError, create_access_token, decode_access_token, hash_password, validate_auth_configuration
from backend.app.repositories.device_repository import DeviceRepository
from backend.app.repositories.metric_repository import MetricRepository
from backend.app.services.monitoring_service import utcnow


TEST_API_KEY = "test-internal-key"
API_HEADERS = {"x-api-key": TEST_API_KEY}


def run(coro):
    return asyncio.run(coro)


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
    import backend.app.services.pipeline_control as pipeline_control_module
    import backend.app.services.run_cycle_service as run_cycle_module

    original_init_db = main_module.init_db
    original_main_app_env = main_module.settings.app_env
    original_scheduler_enabled = main_module.settings.scheduler_enabled
    original_session_local = main_module.SessionLocal
    original_main_api_key = main_module.settings.internal_api_key
    original_main_auth_jwt_secret = main_module.settings.auth_jwt_secret
    original_main_auth_password_secret = main_module.settings.auth_password_secret
    original_main_cookie_secure = main_module.settings.auth_cookie_secure
    original_main_trusted_hosts = main_module.settings.trusted_hosts
    original_main_cors_origins = main_module.settings.cors_origins
    original_deps_api_key = deps_module.settings.internal_api_key
    original_deps_cookie_secure = deps_module.settings.auth_cookie_secure
    original_pipeline_engine = pipeline_control_module.engine
    original_run_cycle_session_local = run_cycle_module.SessionLocal

    async def fake_init_db():
        return None

    main_module.init_db = fake_init_db
    main_module.settings.app_env = "development"
    main_module.settings.scheduler_enabled = False
    main_module.SessionLocal = TestingSessionLocal
    main_module.settings.internal_api_key = TEST_API_KEY
    main_module.settings.auth_jwt_secret = "test-jwt-secret"
    main_module.settings.auth_password_secret = "test-password-secret"
    main_module.settings.auth_cookie_secure = False
    main_module.settings.trusted_hosts = "localhost,127.0.0.1"
    main_module.settings.cors_origins = "http://localhost:8501,http://127.0.0.1:8501"
    deps_module.settings.internal_api_key = TEST_API_KEY
    deps_module.settings.auth_cookie_secure = False
    pipeline_control_module.engine = engine
    run_cycle_module.SessionLocal = TestingSessionLocal

    try:
        with TestClient(app) as client:
            yield client, TestingSessionLocal
    finally:
        main_module.init_db = original_init_db
        main_module.settings.app_env = original_main_app_env
        main_module.settings.scheduler_enabled = original_scheduler_enabled
        main_module.SessionLocal = original_session_local
        main_module.settings.internal_api_key = original_main_api_key
        main_module.settings.auth_jwt_secret = original_main_auth_jwt_secret
        main_module.settings.auth_password_secret = original_main_auth_password_secret
        main_module.settings.auth_cookie_secure = original_main_cookie_secure
        main_module.settings.trusted_hosts = original_main_trusted_hosts
        main_module.settings.cors_origins = original_main_cors_origins
        deps_module.settings.internal_api_key = original_deps_api_key
        deps_module.settings.auth_cookie_secure = original_deps_cookie_secure
        pipeline_control_module.engine = original_pipeline_engine
        run_cycle_module.SessionLocal = original_run_cycle_session_local
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


async def _create_user(session_factory, *, username: str, password: str, role: str = "viewer", full_name: str = "Test User"):
    async with session_factory() as db:
        user = User(
            username=username,
            full_name=full_name,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user


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

        response = client.get("/devices", headers=API_HEADERS)
        status_summary_response = client.get("/devices/status-summary", headers=API_HEADERS)

        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 2
        assert {item["latest_status"] for item in payload} == {"up", "down"}
        assert status_summary_response.status_code == 200
        assert status_summary_response.json() == {"down": 1, "up": 1}


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

        summary_response = client.get("/dashboard/summary", headers=API_HEADERS)
        alerts_response = client.get("/alerts/active", headers=API_HEADERS)
        history_response = client.get("/metrics/history?limit=10", headers=API_HEADERS)

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


def test_dashboard_summary_uses_mikrotik_api_health_without_ping():
    with client_context() as (client, session_factory):
        async def scenario():
            async with session_factory() as db:
                devices = await DeviceRepository(db).upsert_devices(
                    [
                        {"name": "Mikrotik Utama", "ip_address": "192.168.1.254", "device_type": "internet_target"},
                    ]
                )
                await MetricRepository(db).create_metrics(
                    [
                        {
                            "device_id": devices[0].id,
                            "metric_name": "mikrotik_api",
                            "metric_value": "reachable",
                            "status": "ok",
                            "unit": None,
                            "checked_at": utcnow(),
                        },
                    ]
                )

        run(scenario())

        summary_response = client.get("/dashboard/summary", headers=API_HEADERS)

        assert summary_response.status_code == 200
        assert summary_response.json()["mikrotik_status"] == "up"


def test_auth_login_me_and_logout_flow():
    with client_context() as (client, session_factory):
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))

        login_response = client.post(
            "/auth/login",
            json={"username": "viewer", "password": "StrongPass123!", "remember": True},
        )

        assert login_response.status_code == 200
        payload = login_response.json()
        token = payload["access_token"]
        assert token.count(".") == 2
        assert payload["user"]["role"] == "viewer"
        assert login_response.cookies.get("network_monitoring_session") == token
        assert login_response.cookies.get("network_monitoring_refresh") is not None

        restore_response = client.post("/auth/restore")
        assert restore_response.status_code == 200
        restored_token = restore_response.json()["access_token"]
        assert restored_token.count(".") == 2
        assert restored_token != ""
        assert restored_token != token

        me_response = client.get("/auth/me", headers={"authorization": f"Bearer {token}"})
        assert me_response.status_code == 200
        assert me_response.json()["username"] == "viewer"

        me_with_cookie = client.get("/auth/me")
        assert me_with_cookie.status_code == 200
        assert me_with_cookie.json()["username"] == "viewer"

        sessions_with_cookie = client.get("/auth/sessions")
        assert sessions_with_cookie.status_code == 401

        protected_with_cookie = client.get("/devices")
        assert protected_with_cookie.status_code == 401

        logout_response = client.post("/auth/logout", headers={"authorization": f"Bearer {token}"})
        assert logout_response.status_code == 200
        assert client.cookies.get("network_monitoring_session") is None
        assert client.cookies.get("network_monitoring_refresh") is None

        me_after_logout = client.get("/auth/me", headers={"authorization": f"Bearer {token}"})
        assert me_after_logout.status_code == 401
        restore_after_logout = client.post("/auth/restore")
        assert restore_after_logout.status_code == 401


def test_auth_me_prefers_bearer_token_over_cookie_session():
    with client_context() as (client_a, session_factory):
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer", full_name="Viewer User"))
        run(_create_user(session_factory, username="adminuser", password="StrongPass123!", role="admin", full_name="Admin User"))

        viewer_login = client_a.post("/auth/login", json={"username": "viewer", "password": "StrongPass123!"})
        assert viewer_login.status_code == 200

        with TestClient(app) as client_b:
            admin_login = client_b.post("/auth/login", json={"username": "adminuser", "password": "StrongPass123!"})
            assert admin_login.status_code == 200

            mixed_me_response = client_a.get(
                "/auth/me",
                headers={"authorization": f"Bearer {admin_login.json()['access_token']}"},
            )

        assert mixed_me_response.status_code == 200
        assert mixed_me_response.json()["username"] == "adminuser"


def test_write_routes_ignore_cookie_even_when_cookie_user_is_admin():
    with client_context() as (client_a, session_factory):
        run(_create_user(session_factory, username="adminuser", password="StrongPass123!", role="admin", full_name="Admin User"))
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer", full_name="Viewer User"))

        admin_login = client_a.post("/auth/login", json={"username": "adminuser", "password": "StrongPass123!"})
        assert admin_login.status_code == 200

        with TestClient(app) as client_b:
            viewer_login = client_b.post("/auth/login", json={"username": "viewer", "password": "StrongPass123!"})
            assert viewer_login.status_code == 200

            mixed_write_response = client_a.post(
                "/devices",
                headers={"authorization": f"Bearer {viewer_login.json()['access_token']}"},
                json={"name": "Mixed Auth Device", "ip_address": "192.168.1.222", "device_type": "switch"},
            )

        assert mixed_write_response.status_code == 403


def test_auth_requires_dedicated_password_and_jwt_secrets():
    import backend.app.core.security as security_module

    original_password_secret = security_module.settings.auth_password_secret
    original_jwt_secret = security_module.settings.auth_jwt_secret
    original_api_key = security_module.settings.internal_api_key
    original_bootstrap_password = security_module.settings.bootstrap_admin_password

    security_module.settings.auth_password_secret = ""
    security_module.settings.auth_jwt_secret = ""
    security_module.settings.internal_api_key = "legacy-api-key"
    security_module.settings.bootstrap_admin_password = "legacy-bootstrap-password"

    try:
        try:
            validate_auth_configuration()
            assert False, "validate_auth_configuration should fail when dedicated auth secrets are missing"
        except AuthConfigurationError as exc:
            assert "AUTH_PASSWORD_SECRET" in str(exc) or "AUTH_JWT_SECRET" in str(exc)
    finally:
        security_module.settings.auth_password_secret = original_password_secret
        security_module.settings.auth_jwt_secret = original_jwt_secret
        security_module.settings.internal_api_key = original_api_key
        security_module.settings.bootstrap_admin_password = original_bootstrap_password


def test_production_auth_validation_rejects_insecure_defaults():
    import backend.app.core.security as security_module

    original_app_env = security_module.settings.app_env
    original_password_secret = security_module.settings.auth_password_secret
    original_jwt_secret = security_module.settings.auth_jwt_secret
    original_internal_api_key = security_module.settings.internal_api_key
    original_cookie_secure = security_module.settings.auth_cookie_secure
    original_trusted_hosts = security_module.settings.trusted_hosts
    original_cors_origins = security_module.settings.cors_origins
    original_allow_insecure = security_module.settings.allow_insecure_no_auth

    security_module.settings.app_env = "production"
    security_module.settings.auth_password_secret = "test-password-secret"
    security_module.settings.auth_jwt_secret = "test-jwt-secret"
    security_module.settings.internal_api_key = "test-internal-key"
    security_module.settings.auth_cookie_secure = False
    security_module.settings.trusted_hosts = "localhost,127.0.0.1"
    security_module.settings.cors_origins = "https://dashboard.example.com"
    security_module.settings.allow_insecure_no_auth = False

    try:
        try:
            validate_auth_configuration()
            assert False, "validate_auth_configuration should fail when production uses insecure defaults"
        except AuthConfigurationError as exc:
            assert "AUTH_COOKIE_SECURE" in str(exc)
    finally:
        security_module.settings.app_env = original_app_env
        security_module.settings.auth_password_secret = original_password_secret
        security_module.settings.auth_jwt_secret = original_jwt_secret
        security_module.settings.internal_api_key = original_internal_api_key
        security_module.settings.auth_cookie_secure = original_cookie_secure
        security_module.settings.trusted_hosts = original_trusted_hosts
        security_module.settings.cors_origins = original_cors_origins
        security_module.settings.allow_insecure_no_auth = original_allow_insecure


def test_production_auth_validation_accepts_hardened_defaults():
    import backend.app.core.security as security_module

    original_app_env = security_module.settings.app_env
    original_password_secret = security_module.settings.auth_password_secret
    original_jwt_secret = security_module.settings.auth_jwt_secret
    original_internal_api_key = security_module.settings.internal_api_key
    original_internal_api_keys = security_module.settings.internal_api_keys
    original_cookie_secure = security_module.settings.auth_cookie_secure
    original_trusted_hosts = security_module.settings.trusted_hosts
    original_cors_origins = security_module.settings.cors_origins
    original_allow_insecure = security_module.settings.allow_insecure_no_auth

    security_module.settings.app_env = "production"
    security_module.settings.auth_password_secret = "test-password-secret"
    security_module.settings.auth_jwt_secret = "test-jwt-secret"
    security_module.settings.internal_api_key = ""
    security_module.settings.internal_api_keys = "reader:test-internal-key:read"
    security_module.settings.auth_cookie_secure = True
    security_module.settings.trusted_hosts = "api.example.com,dashboard.example.com"
    security_module.settings.cors_origins = "https://dashboard.example.com"
    security_module.settings.allow_insecure_no_auth = False

    try:
        validate_auth_configuration()
    finally:
        security_module.settings.app_env = original_app_env
        security_module.settings.auth_password_secret = original_password_secret
        security_module.settings.auth_jwt_secret = original_jwt_secret
        security_module.settings.internal_api_key = original_internal_api_key
        security_module.settings.internal_api_keys = original_internal_api_keys
        security_module.settings.auth_cookie_secure = original_cookie_secure
        security_module.settings.trusted_hosts = original_trusted_hosts
        security_module.settings.cors_origins = original_cors_origins
        security_module.settings.allow_insecure_no_auth = original_allow_insecure


def test_refresh_cookie_cannot_authenticate_api_requests_directly():
    with client_context() as (client, session_factory):
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))

        login_response = client.post("/auth/login", json={"username": "viewer", "password": "StrongPass123!"})
        assert login_response.status_code == 200
        refresh_token = login_response.cookies.get("network_monitoring_refresh")
        assert refresh_token

        client.cookies.set("network_monitoring_session", "")
        me_response = client.get("/auth/me")
        assert me_response.status_code == 401

        restore_response = client.post("/auth/restore")
        assert restore_response.status_code == 200


def test_logout_clears_refresh_cookie_even_when_access_token_has_expired():
    with client_context() as (client, session_factory):
        user = run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))

        login_response = client.post("/auth/login", json={"username": "viewer", "password": "StrongPass123!"})
        assert login_response.status_code == 200
        refresh_token = login_response.cookies.get("network_monitoring_refresh")
        assert refresh_token

        payload = decode_access_token(login_response.json()["access_token"])
        expired_token = create_access_token(
            subject=user.id,
            username=user.username,
            role=user.role,
            jwt_id=payload.jwt_id,
            expires_at=utcnow() - timedelta(minutes=1),
            access_nonce="expired-access-token",
        )

        logout_response = client.post("/auth/logout", headers={"authorization": f"Bearer {expired_token}"})
        assert logout_response.status_code == 200
        assert client.cookies.get("network_monitoring_session") is None
        assert client.cookies.get("network_monitoring_refresh") is None

        restore_response = client.post("/auth/restore")
        assert restore_response.status_code == 401


def test_bearer_read_requests_do_not_update_last_seen_until_refresh():
    with client_context() as (client, session_factory):
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))

        login_response = client.post("/auth/login", json={"username": "viewer", "password": "StrongPass123!"})
        assert login_response.status_code == 200
        token = login_response.json()["access_token"]
        jwt_id = decode_access_token(token).jwt_id
        baseline_seen_at = utcnow() - timedelta(hours=1)

        async def set_last_seen() -> None:
            async with session_factory() as db:
                session = await db.scalar(select(AuthSession).where(AuthSession.jwt_id == jwt_id))
                assert session is not None
                session.last_seen_at = baseline_seen_at
                await db.commit()

        async def get_last_seen():
            async with session_factory() as db:
                session = await db.scalar(select(AuthSession).where(AuthSession.jwt_id == jwt_id))
                assert session is not None
                return session.last_seen_at

        run(set_last_seen())

        me_response = client.get("/auth/me", headers={"authorization": f"Bearer {token}"})
        assert me_response.status_code == 200
        assert run(get_last_seen()) == baseline_seen_at

        restore_response = client.post("/auth/restore")
        assert restore_response.status_code == 200
        assert run(get_last_seen()) > baseline_seen_at


def test_access_cookie_cannot_be_used_as_refresh_token_when_refresh_cookie_is_missing():
    with client_context() as (client, session_factory):
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))

        login_response = client.post("/auth/login", json={"username": "viewer", "password": "StrongPass123!"})
        assert login_response.status_code == 200
        access_token = login_response.cookies.get("network_monitoring_session")
        assert access_token

        client.cookies.delete("network_monitoring_refresh")
        restore_response = client.post("/auth/restore")
        assert restore_response.status_code == 401


def test_login_rate_limit_blocks_repeated_failed_attempts():
    with client_context() as (client, session_factory):
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))

        for _ in range(5):
            failed_response = client.post("/auth/login", json={"username": "viewer", "password": "wrong-password"})
            assert failed_response.status_code == 401

        rate_limited_response = client.post("/auth/login", json={"username": "viewer", "password": "wrong-password"})
        assert rate_limited_response.status_code == 429
        assert rate_limited_response.json()["detail"] == "Too many login attempts. Please try again later."


def test_refresh_token_reuse_revokes_session_chain():
    with client_context() as (client, session_factory):
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))

        login_response = client.post("/auth/login", json={"username": "viewer", "password": "StrongPass123!"})
        assert login_response.status_code == 200
        original_refresh = login_response.cookies.get("network_monitoring_refresh")
        assert original_refresh

        restore_response = client.post("/auth/restore")
        assert restore_response.status_code == 200
        rotated_access = restore_response.json()["access_token"]
        rotated_refresh = restore_response.cookies.get("network_monitoring_refresh")
        assert rotated_refresh
        assert rotated_refresh != original_refresh

        client.cookies.set("network_monitoring_refresh", original_refresh)
        client.cookies.delete("network_monitoring_session")
        reuse_response = client.post("/auth/restore")
        assert reuse_response.status_code == 401

        client.cookies.set("network_monitoring_refresh", rotated_refresh)
        restore_after_reuse = client.post("/auth/restore")
        assert restore_after_reuse.status_code == 401

        me_after_reuse = client.get("/auth/me", headers={"authorization": f"Bearer {rotated_access}"})
        assert me_after_reuse.status_code == 401


def test_login_uses_forwarded_ip_only_for_trusted_proxy():
    import backend.app.api.routes.auth as auth_route_module

    original_trusted_proxies = auth_route_module.settings.trusted_proxy_ips
    auth_route_module.settings.trusted_proxy_ips = "testclient"
    try:
        with client_context() as (client, session_factory):
            run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))

            for _ in range(5):
                failed_response = client.post(
                    "/auth/login",
                    headers={"x-forwarded-for": "198.51.100.10"},
                    json={"username": "viewer", "password": "wrong-password"},
                )
                assert failed_response.status_code == 401

            rate_limited_response = client.post(
                "/auth/login",
                headers={"x-forwarded-for": "198.51.100.10"},
                json={"username": "viewer", "password": "wrong-password"},
            )
            assert rate_limited_response.status_code == 429
    finally:
        auth_route_module.settings.trusted_proxy_ips = original_trusted_proxies


def test_user_can_list_active_sessions_with_current_marker():
    with client_context() as (client, session_factory):
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))

        login_response = client.post(
            "/auth/login",
            headers={"user-agent": "SessionTestAgent/1.0"},
            json={"username": "viewer", "password": "StrongPass123!"},
        )
        assert login_response.status_code == 200

        sessions_response = client.get("/auth/sessions", headers={"authorization": f"Bearer {login_response.json()['access_token']}"})
        assert sessions_response.status_code == 200
        payload = sessions_response.json()
        assert len(payload) == 1
        assert payload[0]["is_current"] is True
        assert payload[0]["user_agent"] == "SessionTestAgent/1.0"


def test_logout_all_revokes_other_sessions_but_keeps_current_session():
    with client_context() as (client_a, session_factory):
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))

        login_a = client_a.post(
            "/auth/login",
            headers={"user-agent": "ClientA/1.0"},
            json={"username": "viewer", "password": "StrongPass123!"},
        )
        assert login_a.status_code == 200
        token_a = login_a.json()["access_token"]

        with TestClient(app) as client_b:
            login_b = client_b.post(
                "/auth/login",
                headers={"user-agent": "ClientB/1.0"},
                json={"username": "viewer", "password": "StrongPass123!"},
            )
            assert login_b.status_code == 200
            token_b = login_b.json()["access_token"]

            sessions_before = client_a.get("/auth/sessions", headers={"authorization": f"Bearer {token_a}"})
            assert sessions_before.status_code == 200
            assert len(sessions_before.json()) == 2

            logout_all_response = client_a.post("/auth/logout-all", headers={"authorization": f"Bearer {token_a}"})
            assert logout_all_response.status_code == 200
            assert logout_all_response.json()["revoked_sessions"] == 1

            current_me = client_a.get("/auth/me", headers={"authorization": f"Bearer {token_a}"})
            revoked_me = client_b.get("/auth/me", headers={"authorization": f"Bearer {token_b}"})
            sessions_after = client_a.get("/auth/sessions", headers={"authorization": f"Bearer {token_a}"})

            assert current_me.status_code == 200
            assert revoked_me.status_code == 401
            assert sessions_after.status_code == 200
            assert len(sessions_after.json()) == 1
            assert sessions_after.json()[0]["is_current"] is True


def test_admin_can_inspect_and_revoke_user_sessions():
    with client_context() as (client, session_factory):
        viewer_user = run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))
        run(_create_user(session_factory, username="adminuser", password="StrongPass123!", role="admin", full_name="Admin User"))
        admin_login = client.post("/auth/login", json={"username": "adminuser", "password": "StrongPass123!"})
        assert admin_login.status_code == 200
        admin_token = admin_login.json()["access_token"]

        user_login = client.post(
            "/auth/login",
            headers={"user-agent": "ViewerClient/1.0"},
            json={"username": "viewer", "password": "StrongPass123!"},
        )
        assert user_login.status_code == 200

        sessions_response = client.get("/auth/admin/sessions?username=viewer", headers={"authorization": f"Bearer {admin_token}"})
        assert sessions_response.status_code == 200
        sessions_payload = sessions_response.json()
        assert len(sessions_payload) >= 1
        assert sessions_payload[0]["username"] == "viewer"

        revoked_response = client.post(
            f"/auth/admin/users/{viewer_user.id}/logout-all",
            headers={"authorization": f"Bearer {admin_token}"},
        )
        assert revoked_response.status_code == 200
        assert revoked_response.json()["revoked_sessions"] >= 1


def test_viewer_cannot_access_admin_mutation_routes():
    with client_context() as (client, session_factory):
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))

        login_response = client.post("/auth/login", json={"username": "viewer", "password": "StrongPass123!"})
        token = login_response.json()["access_token"]

        create_response = client.post(
            "/devices",
            headers={"authorization": f"Bearer {token}"},
            json={"name": "Viewer Device", "ip_address": "192.168.1.202", "device_type": "switch"},
        )
        assert create_response.status_code == 403


def test_admin_bearer_token_can_access_read_and_write_routes():
    with client_context() as (client, session_factory):
        run(_create_user(session_factory, username="adminuser", password="StrongPass123!", role="admin", full_name="Admin User"))

        login_response = client.post("/auth/login", json={"username": "adminuser", "password": "StrongPass123!"})
        token = login_response.json()["access_token"]
        headers = {"authorization": f"Bearer {token}"}

        list_response = client.get("/devices", headers=headers)
        create_response = client.post(
            "/devices",
            headers=headers,
            json={"name": "Admin Device", "ip_address": "192.168.1.203", "device_type": "switch"},
        )

        assert list_response.status_code == 200
        assert create_response.status_code == 201


def test_dashboard_overview_panels_and_problem_devices_endpoints():
    with client_context() as (client, session_factory):
        async def scenario():
            async with session_factory() as db:
                devices = await DeviceRepository(db).upsert_devices(
                    [
                        {"name": "Gateway Lokal", "ip_address": "192.168.1.1", "device_type": "internet_target"},
                        {"name": "Server Monitoring", "ip_address": "192.168.1.10", "device_type": "server"},
                    ]
                )
                now = utcnow()
                await MetricRepository(db).create_metrics(
                    [
                        {
                            "device_id": devices[0].id,
                            "metric_name": "ping",
                            "metric_value": "timeout",
                            "status": "down",
                            "unit": None,
                            "checked_at": now,
                        },
                        {
                            "device_id": devices[1].id,
                            "metric_name": "ping",
                            "metric_value": "2.50",
                            "status": "up",
                            "unit": "ms",
                            "checked_at": now,
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
                        created_at=now,
                    )
                )
                await db.commit()

        run(scenario())

        panels_response = client.get("/dashboard/overview-panels", headers=API_HEADERS)
        problem_devices_response = client.get("/dashboard/problem-devices?limit=25", headers=API_HEADERS)
        compatibility_response = client.get("/dashboard/overview-data", headers=API_HEADERS)

        assert panels_response.status_code == 200
        payload = panels_response.json()
        assert payload["summary"]["internet_status"] == "down"
        assert payload["summary"]["server_status"] == "up"
        assert payload["summary"]["active_alerts"] == 1
        assert payload["device_counts"]["total"] == 2
        assert payload["device_counts"]["active"] == 2
        assert payload["device_counts"]["statuses"]["down"] == 1
        assert len(payload["alerts"]) == 1
        assert payload["latest_snapshot"]["meta"]["total"] >= 2
        assert problem_devices_response.status_code == 200
        assert len(problem_devices_response.json()) == 1
        assert compatibility_response.status_code == 200
        assert "problem_devices" in compatibility_response.json()


def test_create_update_and_delete_device_endpoint():
    with client_context() as (client, session_factory):
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

        async def seed_related_rows():
            async with session_factory() as db:
                await MetricRepository(db).create_metrics(
                    [
                        {
                            "device_id": created_payload["id"],
                            "metric_name": "ping",
                            "metric_value": "12",
                            "status": "up",
                            "unit": "ms",
                            "checked_at": utcnow(),
                        }
                    ]
                )
                db.add(
                    Alert(
                        device_id=created_payload["id"],
                        alert_type="device_down",
                        severity="critical",
                        message="AP Lobby Updated is unreachable",
                        status="active",
                        created_at=utcnow(),
                    )
                )
                await db.commit()

        run(seed_related_rows())

        delete_response = client.delete(f'/devices/{created_payload["id"]}', headers=API_HEADERS)
        get_deleted_response = client.get(f'/devices/{created_payload["id"]}', headers=API_HEADERS)

        async def fetch_alert_device_id():
            async with session_factory() as db:
                return await db.scalar(select(Alert.device_id).where(Alert.alert_type == "device_down"))

        assert delete_response.status_code == 204
        assert get_deleted_response.status_code == 404
        assert run(fetch_alert_device_id()) is None


def test_device_type_metadata_and_validation():
    with client_context() as (client, _session_factory):
        types_response = client.get("/devices/meta/types", headers=API_HEADERS)
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
        assert any(item["value"] == "voip" for item in types_payload)

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

        response = client.get(
            f"/metrics/history?device_id={server_device_id}&metric_name=cpu_percent&status=warning",
            headers=API_HEADERS,
        )
        names_response = client.get(f"/metrics/names?device_id={server_device_id}", headers=API_HEADERS)

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

        filtered_response = client.get(
            "/devices?active_only=true&device_type=access_point&latest_status=down&search=Lobby",
            headers=API_HEADERS,
        )
        paged_response = client.get("/devices?limit=1&offset=1", headers=API_HEADERS)

        assert filtered_response.status_code == 200
        filtered_payload = filtered_response.json()
        assert len(filtered_payload) == 1
        assert filtered_payload[0]["name"] == "AP Lobby"

        assert paged_response.status_code == 200
        assert len(paged_response.json()) == 1

        paged_meta_response = client.get("/devices/paged?active_only=true&limit=1&offset=0", headers=API_HEADERS)
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

        response = client.get(
            f"/metrics/history?metric_name=cpu_percent&checked_from={checked_from}&checked_to={checked_to}",
            headers=API_HEADERS,
        )

        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 1
        assert payload[0]["metric_value"] == "35.00"

        paged_response = client.get(
            f"/metrics/history/paged?metric_name=cpu_percent&checked_from={checked_from}&checked_to={checked_to}&limit=10&offset=0",
            headers=API_HEADERS,
        )
        assert paged_response.status_code == 200
        paged_payload = paged_response.json()
        assert paged_payload["meta"]["total"] == 1
        assert len(paged_payload["items"]) == 1


def test_metrics_history_paged_supports_bulk_metric_names_with_per_metric_limit():
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
                            "checked_at": now - timedelta(minutes=10),
                        },
                        {
                            "device_id": devices[0].id,
                            "metric_name": "cpu_percent",
                            "metric_value": "20.00",
                            "status": "ok",
                            "unit": "%",
                            "checked_at": now - timedelta(minutes=5),
                        },
                        {
                            "device_id": devices[0].id,
                            "metric_name": "memory_percent",
                            "metric_value": "60.00",
                            "status": "warning",
                            "unit": "%",
                            "checked_at": now - timedelta(minutes=8),
                        },
                        {
                            "device_id": devices[0].id,
                            "metric_name": "memory_percent",
                            "metric_value": "70.00",
                            "status": "warning",
                            "unit": "%",
                            "checked_at": now - timedelta(minutes=3),
                        },
                    ]
                )
                return devices[0].id

        device_id = run(scenario())
        response = client.get(
            f"/metrics/history/paged?device_id={device_id}&metric_names=cpu_percent&metric_names=memory_percent&per_metric_limit=1&limit=500&offset=0",
            headers=API_HEADERS,
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["meta"]["total"] == 2
        assert len(payload["items"]) == 2
        metric_names = sorted(item["metric_name"] for item in payload["items"])
        assert metric_names == ["cpu_percent", "memory_percent"]


def test_latest_snapshot_endpoint_is_unfiltered_and_paged():
    with client_context() as (client, session_factory):
        async def scenario():
            async with session_factory() as db:
                devices = await DeviceRepository(db).upsert_devices(
                    [
                        {"name": "AP Alpha", "ip_address": "192.168.1.40", "device_type": "access_point"},
                        {"name": "Printer Bravo", "ip_address": "192.168.1.50", "device_type": "printer"},
                    ]
                )
                now = utcnow()
                await MetricRepository(db).create_metrics(
                    [
                        {
                            "device_id": devices[0].id,
                            "metric_name": "ping",
                            "metric_value": "30.00",
                            "status": "up",
                            "unit": "ms",
                            "checked_at": now - timedelta(minutes=5),
                        },
                        {
                            "device_id": devices[0].id,
                            "metric_name": "ping",
                            "metric_value": "10.00",
                            "status": "up",
                            "unit": "ms",
                            "checked_at": now,
                        },
                        {
                            "device_id": devices[0].id,
                            "metric_name": "cpu_percent",
                            "metric_value": "80.00",
                            "status": "warning",
                            "unit": "%",
                            "checked_at": now,
                        },
                        {
                            "device_id": devices[1].id,
                            "metric_name": "ping",
                            "metric_value": "timeout",
                            "status": "down",
                            "unit": None,
                            "checked_at": now,
                        },
                    ]
                )

        run(scenario())

        response = client.get("/metrics/latest-snapshot/paged?limit=1&offset=0", headers=API_HEADERS)
        status_summary_response = client.get("/metrics/latest-snapshot/status-summary", headers=API_HEADERS)
        uptime_map_response = client.get("/metrics/latest-snapshot/uptime-map?limit=2&offset=0", headers=API_HEADERS)

        assert response.status_code == 200
        payload = response.json()
        assert payload["meta"]["total"] == 3
        assert payload["meta"]["limit"] == 1
        assert len(payload["items"]) == 1
        assert payload["items"][0]["device_name"] == "AP Alpha"
        assert payload["items"][0]["metric_name"] == "cpu_percent"
        assert payload["items"][0]["metric_value"] == "80.00"
        assert status_summary_response.status_code == 200
        assert status_summary_response.json() == {"down": 1, "warning": 1}
        assert uptime_map_response.status_code == 200
        uptime_map = uptime_map_response.json()
        assert uptime_map
        assert any(value == "300" for value in uptime_map.values())


def test_metrics_history_context_endpoint():
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
                            "metric_value": "35.00",
                            "status": "warning",
                            "unit": "%",
                            "checked_at": now,
                        },
                        {
                            "device_id": devices[0].id,
                            "metric_name": "memory_percent",
                            "metric_value": "70.00",
                            "status": "ok",
                            "unit": "%",
                            "checked_at": now,
                        },
                    ]
                )
                return devices[0].id

        device_id = run(scenario())
        response = client.get(
            f"/metrics/history/context?device_id={device_id}&metric_name=cpu_percent&status=warning&limit=50&selected_device_limit=25&snapshot_limit=10&snapshot_offset=0",
            headers=API_HEADERS,
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["metric_names"] == ["cpu_percent", "memory_percent"]
        assert payload["history"]["meta"]["total"] == 1
        assert len(payload["history"]["items"]) == 1
        assert payload["selected_device_history"]["meta"]["total"] == 1
        assert len(payload["selected_device_history"]["items"]) == 1
        assert "latest_snapshot" in payload
        assert "latest_snapshot_status_summary" in payload
        assert "snapshot_uptime_map" in payload


def test_latest_snapshot_status_summary_preserves_fallback_first_status_behavior():
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
                            "metric_value": "55.00",
                            "status": "ok",
                            "unit": "%",
                            "checked_at": now,
                        },
                        {
                            "device_id": devices[0].id,
                            "metric_name": "memory_percent",
                            "metric_value": "65.00",
                            "status": "weird_state",
                            "unit": "%",
                            "checked_at": now,
                        },
                    ]
                )

        run(scenario())
        response = client.get("/metrics/latest-snapshot/status-summary", headers=API_HEADERS)
        context_response = client.get("/metrics/history/context?snapshot_limit=10&snapshot_offset=0", headers=API_HEADERS)

        assert response.status_code == 200
        assert context_response.status_code == 200
        status_summary = response.json()
        context_summary = context_response.json()["latest_snapshot_status_summary"]
        assert status_summary == {"ok": 1}
        assert context_summary == status_summary


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
            incidents_response = client.get("/incidents?status=active", headers=API_HEADERS)
            alerts_response = client.get("/alerts/active", headers=API_HEADERS)
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
        list_response = client.get("/thresholds", headers=API_HEADERS)

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
        assert any(item["key"] == "mikrotik_connected_clients_warning" for item in payload)
        assert any(item["key"] == "mikrotik_interface_mbps_warning" for item in payload)
        assert any(item["key"] == "mikrotik_firewall_spike_pps_warning" for item in payload)
        assert any(item["key"] == "mikrotik_firewall_spike_mbps_warning" for item in payload)
        assert any(item["key"] == "printer_ink_warning" for item in payload)
        assert any(item["key"] == "printer_ink_critical" for item in payload)

        update_response = client.put("/thresholds/cpu_warning", headers=API_HEADERS, json={"value": 92})
        assert update_response.status_code == 200
        assert update_response.json()["value"] == 92

        list_response_after = client.get("/thresholds", headers=API_HEADERS)
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
            alerts_response = client.get("/alerts/active", headers=API_HEADERS)
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


def test_run_cycle_creates_mikrotik_metric_alerts():
    with client_context() as (client, session_factory):
        mikrotik_device_id = run(
            _seed_devices_and_metrics(
                session_factory,
                [{"name": "Mikrotik Utama", "ip_address": "192.168.88.1", "device_type": "internet_target"}],
                [],
            )
        )[0].id

        import backend.app.services.run_cycle_service as run_cycle_module

        original_internet = run_cycle_module.run_internet_checks
        original_device = run_cycle_module.run_device_checks
        original_server = run_cycle_module.run_server_checks
        original_mikrotik = run_cycle_module.run_mikrotik_checks

        async def fake_mikrotik_checks(_db):
            checked_at = utcnow()
            return [
                {
                    "device_id": mikrotik_device_id,
                    "metric_name": "mikrotik_api",
                    "metric_value": "connection_failed",
                    "status": "error",
                    "unit": None,
                    "checked_at": checked_at,
                },
                {
                    "device_id": mikrotik_device_id,
                    "metric_name": "connected_clients",
                    "metric_value": "150",
                    "status": "ok",
                    "unit": "count",
                    "checked_at": checked_at,
                },
                {
                    "device_id": mikrotik_device_id,
                    "metric_name": "interface:ether1-wan:rx_mbps",
                    "metric_value": "95.00",
                    "status": "up",
                    "unit": "Mbps",
                    "checked_at": checked_at,
                },
                {
                    "device_id": mikrotik_device_id,
                    "metric_name": "firewall:filter:001_forward_drop_bad:pps",
                    "metric_value": "1200.00",
                    "status": "warning",
                    "unit": "pps",
                    "checked_at": checked_at,
                },
            ]

        try:
            async def empty_checks(_db):
                return []

            run_cycle_module.run_internet_checks = empty_checks
            run_cycle_module.run_device_checks = empty_checks
            run_cycle_module.run_server_checks = empty_checks
            run_cycle_module.run_mikrotik_checks = fake_mikrotik_checks

            cycle_response = client.post("/system/run-cycle", headers=API_HEADERS)
            alerts_response = client.get("/alerts/active", headers=API_HEADERS)
            incidents_response = client.get("/incidents?status=active", headers=API_HEADERS)
        finally:
            run_cycle_module.run_internet_checks = original_internet
            run_cycle_module.run_device_checks = original_device
            run_cycle_module.run_server_checks = original_server
            run_cycle_module.run_mikrotik_checks = original_mikrotik

        assert cycle_response.status_code == 200
        cycle_payload = cycle_response.json()
        assert cycle_payload["metrics_collected"] == 4
        assert cycle_payload["alerts_created"] == 4
        assert cycle_payload["incidents_created"] == 1

        assert alerts_response.status_code == 200
        alert_types = {alert["alert_type"] for alert in alerts_response.json()}
        assert alert_types == {
            "mikrotik_api_failed",
            "mikrotik_connected_clients_high",
            "mikrotik_interface_traffic_high",
            "mikrotik_firewall_spike",
        }
        assert incidents_response.status_code == 200
        assert len(incidents_response.json()) == 1


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
            alerts_response = client.get("/alerts/active", headers=API_HEADERS)
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


def test_run_cycle_creates_printer_alerts_and_incident():
    with client_context() as (client, session_factory):
        printer_device_id = run(
            _seed_devices_and_metrics(
                session_factory,
                [{"name": "EPSON L3250 - 1", "ip_address": "192.168.88.38", "device_type": "printer"}],
                lambda devices: [
                    {
                        "device_id": devices[0].id,
                        "metric_name": "printer_uptime_seconds",
                        "metric_value": "7200",
                        "status": "ok",
                        "unit": "s",
                        "checked_at": utcnow() - timedelta(minutes=5),
                    }
                ],
            )
        )[0].id

        import backend.app.services.run_cycle_service as run_cycle_module

        original_internet = run_cycle_module.run_internet_checks
        original_device = run_cycle_module.run_device_checks
        original_server = run_cycle_module.run_server_checks
        original_mikrotik = run_cycle_module.run_mikrotik_checks

        async def fake_device_checks(_db):
            now = utcnow()
            return [
                {
                    "device_id": printer_device_id,
                    "metric_name": "ping",
                    "metric_value": "4.00",
                    "status": "up",
                    "unit": "ms",
                    "checked_at": now,
                },
                {
                    "device_id": printer_device_id,
                    "metric_name": "printer_uptime_seconds",
                    "metric_value": "90",
                    "status": "ok",
                    "unit": "s",
                    "checked_at": now,
                },
                {
                    "device_id": printer_device_id,
                    "metric_name": "printer_status",
                    "metric_value": "idle",
                    "status": "up",
                    "unit": None,
                    "checked_at": now,
                },
                {
                    "device_id": printer_device_id,
                    "metric_name": "printer_ink_status",
                    "metric_value": "empty",
                    "status": "error",
                    "unit": None,
                    "checked_at": now,
                },
                {
                    "device_id": printer_device_id,
                    "metric_name": "printer_error_state",
                    "metric_value": "jammed",
                    "status": "error",
                    "unit": None,
                    "checked_at": now,
                },
                {
                    "device_id": printer_device_id,
                    "metric_name": "printer_paper_status",
                    "metric_value": "empty",
                    "status": "error",
                    "unit": None,
                    "checked_at": now,
                },
                {
                    "device_id": printer_device_id,
                    "metric_name": "printer_total_pages",
                    "metric_value": "2000",
                    "status": "ok",
                    "unit": "pages",
                    "checked_at": now,
                },
            ]

        try:
            async def empty_checks(_db):
                return []

            run_cycle_module.run_internet_checks = empty_checks
            run_cycle_module.run_device_checks = fake_device_checks
            run_cycle_module.run_server_checks = empty_checks
            run_cycle_module.run_mikrotik_checks = empty_checks

            cycle_response = client.post("/system/run-cycle", headers=API_HEADERS)
            alerts_response = client.get("/alerts/active", headers=API_HEADERS)
            incidents_response = client.get("/incidents?status=active", headers=API_HEADERS)
        finally:
            run_cycle_module.run_internet_checks = original_internet
            run_cycle_module.run_device_checks = original_device
            run_cycle_module.run_server_checks = original_server
            run_cycle_module.run_mikrotik_checks = original_mikrotik

        assert cycle_response.status_code == 200
        cycle_payload = cycle_response.json()
        assert cycle_payload["alerts_created"] == 4
        assert cycle_payload["incidents_created"] == 1

        assert alerts_response.status_code == 200
        alert_types = {alert["alert_type"] for alert in alerts_response.json()}
        assert alert_types == {
            "printer_reboot_detected",
            "printer_error_state",
            "printer_paper_issue",
            "printer_ink_empty",
        }

        assert incidents_response.status_code == 200
        assert len(incidents_response.json()) == 1


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


def test_internal_api_key_scopes_split_write_and_ops_access():
    import backend.app.core.config as config_module

    original_internal_api_key = config_module.settings.internal_api_key
    original_internal_api_keys = config_module.settings.internal_api_keys
    config_module.settings.internal_api_key = ""
    config_module.settings.internal_api_keys = "\n".join(
        [
            "reader:reader-key:read",
            "writer:writer-key:read,write",
            "operator:ops-key:read,ops",
        ]
    )
    config_module._parse_internal_api_key_map.cache_clear()

    try:
        with client_context() as (client, _session_factory):
            read_response = client.get("/devices", headers={"x-api-key": "reader-key"})
            write_denied = client.post(
                "/devices",
                headers={"x-api-key": "reader-key"},
                json={"name": "Blocked Device", "ip_address": "192.168.1.190", "device_type": "switch"},
            )
            write_allowed = client.post(
                "/devices",
                headers={"x-api-key": "writer-key"},
                json={"name": "Writable Device", "ip_address": "192.168.1.191", "device_type": "switch"},
            )
            ops_denied = client.post("/system/run-cycle", headers={"x-api-key": "writer-key"})
            ops_allowed = client.post("/system/run-cycle", headers={"x-api-key": "ops-key"})

        assert read_response.status_code == 200
        assert write_denied.status_code == 403
        assert write_allowed.status_code == 201
        assert ops_denied.status_code == 403
        assert ops_allowed.status_code == 200
    finally:
        config_module.settings.internal_api_key = original_internal_api_key
        config_module.settings.internal_api_keys = original_internal_api_keys
        config_module._parse_internal_api_key_map.cache_clear()


def test_internal_api_key_protects_read_endpoints():
    with client_context() as (client, _session_factory):
        unauthorized_devices = client.get("/devices")
        authorized_devices = client.get("/devices", headers=API_HEADERS)

        assert unauthorized_devices.status_code == 401
        assert authorized_devices.status_code == 200


def test_missing_credentials_are_rejected_without_api_key_or_bearer_token():
    import backend.app.api.deps as deps_module

    with client_context() as (client, _session_factory):
        original_api_key = deps_module.settings.internal_api_key
        deps_module.settings.internal_api_key = ""

        try:
            response = client.post(
                "/devices",
                json={"name": "Missing Key", "ip_address": "192.168.1.91", "device_type": "switch"},
            )
        finally:
            deps_module.settings.internal_api_key = original_api_key

        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required"


def test_admin_user_lifecycle_and_audit_logs():
    with client_context() as (client, session_factory):
        run(_create_user(session_factory, username="adminuser", password="StrongPass123!", role="admin", full_name="Admin User"))

        admin_login = client.post("/auth/login", json={"username": "adminuser", "password": "StrongPass123!"})
        assert admin_login.status_code == 200
        headers = {"authorization": f"Bearer {admin_login.json()['access_token']}"}

        create_response = client.post(
            "/auth/admin/users",
            headers=headers,
            json={
                "username": "viewer2",
                "full_name": "Viewer Two",
                "password": "ViewerTwo@123!",
                "role": "viewer",
            },
        )
        assert create_response.status_code == 200
        created_user = create_response.json()

        update_response = client.put(
            f"/auth/admin/users/{created_user['id']}",
            headers=headers,
            json={"is_active": False, "disabled_reason": "Offboarding"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["is_active"] is False

        reset_response = client.post(
            f"/auth/admin/users/{created_user['id']}/reset-password",
            headers=headers,
            json={"new_password": "ViewerTwo@456!"},
        )
        assert reset_response.status_code == 200

        audit_response = client.get("/auth/admin/audit-logs?limit=20", headers=headers)
        users_response = client.get("/auth/admin/users", headers=headers)

        assert audit_response.status_code == 200
        actions = {item["action"] for item in audit_response.json()}
        assert "auth.admin.create_user" in actions
        assert "auth.admin.update_user" in actions
        assert "auth.admin.reset_password" in actions
        assert users_response.status_code == 200
        assert any(item["username"] == "viewer2" for item in users_response.json())


def test_user_can_change_password_and_old_password_stops_working():
    with client_context() as (client, session_factory):
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))

        login_response = client.post("/auth/login", json={"username": "viewer", "password": "StrongPass123!"})
        assert login_response.status_code == 200
        token = login_response.json()["access_token"]
        headers = {"authorization": f"Bearer {token}"}

        change_response = client.post(
            "/auth/change-password",
            headers=headers,
            json={"current_password": "StrongPass123!", "new_password": "StrongPass456!@"},
        )
        assert change_response.status_code == 200
        assert change_response.json()["username"] == "viewer"

        old_login = client.post("/auth/login", json={"username": "viewer", "password": "StrongPass123!"})
        new_login = client.post("/auth/login", json={"username": "viewer", "password": "StrongPass456!@"})

        assert old_login.status_code == 401
        assert new_login.status_code == 200



def test_health_endpoint_and_request_id_header():
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
