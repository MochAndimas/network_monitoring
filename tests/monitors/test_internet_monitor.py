import asyncio

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.db.base import Base
from backend.app.monitors import helpers
from backend.app.monitors.device import service as device_service
from backend.app.monitors.internet import service as internet_service
from backend.app.monitors.mikrotik import service as mikrotik_service
from backend.app.repositories.device_repository import DeviceRepository
from backend.app.repositories.metric_repository import MetricRepository
from backend.app.services.monitoring_service import utcnow


def run(coro):
    return asyncio.run(coro)


def test_internet_checks_collect_quality_dns_http_and_public_ip(monkeypatch, session_factory):
    ping_samples = iter([0.010, None, 0.020])
    monkeypatch.setattr(helpers.settings, "ping_sample_count", 3)

    async def fake_safe_ping(_ip_address):
        return next(ping_samples)

    monkeypatch.setattr(helpers, "safe_ping", fake_safe_ping)

    async def fake_getaddrinfo(*_args, **_kwargs):
        return [object()]

    class FakeLoop:
        async def getaddrinfo(self, *_args, **_kwargs):
            return await fake_getaddrinfo()

    monkeypatch.setattr(internet_service.asyncio, "get_running_loop", lambda: FakeLoop())

    async def fake_client_get(self, url, **_kwargs):
        request = httpx.Request("GET", url)
        if url == internet_service.settings.public_ip_check_url:
            return httpx.Response(200, request=request, text="203.0.113.20")
        return httpx.Response(204, request=request)

    monkeypatch.setattr(internet_service.httpx.AsyncClient, "get", fake_client_get)

    async def scenario():
        async with session_factory() as db:
            device = (
                await DeviceRepository(db).upsert_devices(
                    [{"name": "Google DNS", "ip_address": "8.8.8.8", "device_type": "internet_target"}]
                )
            )[0]
            await MetricRepository(db).create_metrics(
                [
                    {
                        "device_id": device.id,
                        "metric_name": "public_ip",
                        "metric_value": "203.0.113.10",
                        "status": "up",
                        "unit": None,
                        "checked_at": utcnow(),
                    }
                ]
            )
            return await internet_service.run_internet_checks(db)

    metrics = run(scenario())

    metrics_by_name = {metric["metric_name"]: metric for metric in metrics}
    assert metrics_by_name["ping"]["metric_value"] == "20.00"
    assert metrics_by_name["packet_loss"]["metric_value"] == "33.33"
    assert metrics_by_name["packet_loss"]["status"] == "warning"
    assert metrics_by_name["jitter"]["metric_value"] == "10.00"
    assert metrics_by_name["dns_resolution_time"]["status"] == "up"
    assert metrics_by_name["http_response_time"]["status"] == "up"
    assert metrics_by_name["public_ip"]["metric_value"] == "203.0.113.20"
    assert metrics_by_name["public_ip"]["status"] == "warning"


def test_access_point_and_printer_checks_collect_packet_loss_and_jitter(monkeypatch, session_factory):
    ping_samples = iter([0.010, None, 0.020, 0.030, 0.030, 0.030])
    monkeypatch.setattr(helpers.settings, "ping_sample_count", 3)

    async def fake_safe_ping(_ip_address):
        return next(ping_samples)

    monkeypatch.setattr(helpers, "safe_ping", fake_safe_ping)

    async def scenario():
        async with session_factory() as db:
            devices = await DeviceRepository(db).upsert_devices(
                [
                    {"name": "AP Meeting Room", "ip_address": "192.168.1.40", "device_type": "access_point"},
                    {"name": "Printer Finance", "ip_address": "192.168.1.50", "device_type": "printer"},
                ]
            )
            metrics = await device_service.run_device_checks(db)
            return devices, metrics

    devices, metrics = run(scenario())

    metrics_by_device_and_name = {(metric["device_id"], metric["metric_name"]): metric for metric in metrics}
    metric_names = [metric["metric_name"] for metric in metrics]
    assert metric_names.count("ping") == 2
    assert metric_names.count("packet_loss") == 2
    assert metric_names.count("jitter") == 2
    access_point_id = next(device.id for device in devices if device.device_type == "access_point")
    printer_id = next(device.id for device in devices if device.device_type == "printer")
    assert metrics_by_device_and_name[(access_point_id, "packet_loss")]["metric_value"] == "33.33"
    assert metrics_by_device_and_name[(access_point_id, "jitter")]["metric_value"] == "10.00"
    assert metrics_by_device_and_name[(printer_id, "packet_loss")]["metric_value"] == "0.00"
    assert metrics_by_device_and_name[(printer_id, "jitter")]["metric_value"] == "0.00"


def test_mikrotik_checks_collect_packet_loss_and_jitter(monkeypatch, session_factory):
    ping_samples = iter([0.010, 0.015, 0.025])
    monkeypatch.setattr(helpers.settings, "ping_sample_count", 3)

    async def fake_safe_ping(_ip_address):
        return next(ping_samples)

    monkeypatch.setattr(helpers, "safe_ping", fake_safe_ping)

    async def scenario():
        async with session_factory() as db:
            await DeviceRepository(db).upsert_devices(
                [{"name": "Mikrotik Utama", "ip_address": "192.168.1.254", "device_type": "mikrotik"}]
            )
            return await mikrotik_service.run_mikrotik_checks(db)

    metrics = run(scenario())

    metrics_by_name = {metric["metric_name"]: metric for metric in metrics}
    assert metrics_by_name["ping"]["metric_value"] == "25.00"
    assert metrics_by_name["packet_loss"]["metric_value"] == "0.00"
    assert metrics_by_name["jitter"]["metric_value"] == "7.50"


@pytest.fixture
def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = async_sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    run(_create_all(engine))
    try:
        yield SessionLocal
    finally:
        run(_drop_all(engine))


async def _create_all(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def _drop_all(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()
