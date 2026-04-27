"""Define test module behavior for `tests/api/dashboard_endpoints/common.py`.

This module contains automated regression and validation scenarios.
"""

from contextlib import contextmanager
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.scheduler_job_status import SchedulerJobStatus
from backend.app.models.alert import Alert
from backend.app.models.incident import Incident
from backend.app.models.metric_daily_rollup import MetricDailyRollup
from backend.app.models.user import AuthSession
from backend.app.models.user import User
from backend.app.core.security import AuthConfigurationError, create_access_token, decode_access_token, hash_password, validate_auth_configuration
from backend.app.repositories.device_repository import DeviceRepository
from backend.app.repositories.metric_repository import MetricRepository
from backend.app.core.time import utcnow
from tests.test_utils import create_all, drop_all, empty_checks, run


TEST_API_KEY = "test-internal-key"
API_HEADERS = {"x-api-key": TEST_API_KEY}

@contextmanager

def client_context():
    """Perform client context.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = async_sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    run(create_all(engine))

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
        run(drop_all(engine))

async def _seed_devices_and_metrics(
    session_factory,
    devices_payload: list[dict],
    metrics_payload: list[dict] | Callable[[list], list[dict[str, Any]]],
):
    """Perform seed devices and metrics.

    Args:
        session_factory: Parameter input untuk routine ini.
        devices_payload: Parameter input untuk routine ini.
        metrics_payload: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    async with session_factory() as db:
        devices = await DeviceRepository(db).upsert_devices(devices_payload)
        if metrics_payload:
            await MetricRepository(db).create_metrics(metrics_payload(devices) if callable(metrics_payload) else metrics_payload)
        return devices

async def _create_user(session_factory, *, username: str, password: str, role: str = "viewer", full_name: str = "Test User"):
    """Perform create user.

    Args:
        session_factory: Parameter input untuk routine ini.
        username: Parameter input untuk routine ini.
        password: Parameter input untuk routine ini.
        role: Parameter input untuk routine ini.
        full_name: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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


__all__ = [
    "date",
    "timedelta",
    "TestClient",
    "select",
    "async_sessionmaker",
    "create_async_engine",
    "StaticPool",
    "get_db",
    "app",
    "SchedulerJobStatus",
    "Alert",
    "Incident",
    "MetricDailyRollup",
    "AuthSession",
    "User",
    "AuthConfigurationError",
    "create_access_token",
    "decode_access_token",
    "hash_password",
    "validate_auth_configuration",
    "DeviceRepository",
    "MetricRepository",
    "utcnow",
    "create_all",
    "drop_all",
    "empty_checks",
    "run",
    "TEST_API_KEY",
    "API_HEADERS",
    "client_context",
    "_seed_devices_and_metrics",
    "_create_user",
]

