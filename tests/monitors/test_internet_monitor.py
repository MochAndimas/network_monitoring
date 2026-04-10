import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.base import Base
from backend.app.monitors import helpers
from backend.app.monitors.device import service as device_service
from backend.app.monitors.internet import service as internet_service
from backend.app.monitors.mikrotik import service as mikrotik_service
from backend.app.repositories.device_repository import DeviceRepository
from backend.app.repositories.metric_repository import MetricRepository
from backend.app.services.monitoring_service import utcnow


def test_internet_checks_collect_quality_dns_http_and_public_ip(monkeypatch, session_factory):
    with session_factory() as db:
        device = DeviceRepository(db).upsert_devices(
            [{"name": "Google DNS", "ip_address": "8.8.8.8", "device_type": "internet_target"}]
        )[0]
        MetricRepository(db).create_metrics(
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

        ping_samples = iter([0.010, None, 0.020])
        monkeypatch.setattr(helpers.settings, "ping_sample_count", 3)
        monkeypatch.setattr(helpers, "safe_ping", lambda _ip_address: next(ping_samples))
        monkeypatch.setattr(internet_service.socket, "getaddrinfo", lambda *_args, **_kwargs: [object()])

        def fake_http_get(url, **_kwargs):
            request = httpx.Request("GET", url)
            if url == internet_service.settings.public_ip_check_url:
                return httpx.Response(200, request=request, text="203.0.113.20")
            return httpx.Response(204, request=request)

        monkeypatch.setattr(internet_service.httpx, "get", fake_http_get)

        metrics = internet_service.run_internet_checks(db)

    metrics_by_name = {metric["metric_name"]: metric for metric in metrics}
    assert metrics_by_name["ping"]["metric_value"] == "20.00"
    assert metrics_by_name["packet_loss"]["metric_value"] == "33.33"
    assert metrics_by_name["packet_loss"]["status"] == "warning"
    assert metrics_by_name["jitter"]["metric_value"] == "10.00"
    assert metrics_by_name["dns_resolution_time"]["status"] == "up"
    assert metrics_by_name["http_response_time"]["status"] == "up"
    assert metrics_by_name["public_ip"]["metric_value"] == "203.0.113.20"
    assert metrics_by_name["public_ip"]["status"] == "warning"


def test_access_point_checks_collect_packet_loss_and_jitter(monkeypatch, session_factory):
    with session_factory() as db:
        DeviceRepository(db).upsert_devices(
            [
                {"name": "AP Meeting Room", "ip_address": "192.168.1.40", "device_type": "access_point"},
                {"name": "Printer Finance", "ip_address": "192.168.1.50", "device_type": "printer"},
            ]
        )

        ping_samples = iter([0.010, None, 0.020, 0.030])
        monkeypatch.setattr(helpers.settings, "ping_sample_count", 3)
        monkeypatch.setattr(helpers, "safe_ping", lambda _ip_address: next(ping_samples))

        metrics = device_service.run_device_checks(db)

    metrics_by_device_and_name = {(metric["device_id"], metric["metric_name"]): metric for metric in metrics}
    metric_names = [metric["metric_name"] for metric in metrics]
    assert metric_names.count("ping") == 2
    assert metric_names.count("packet_loss") == 1
    assert metric_names.count("jitter") == 1
    access_point_metric_names = [
        name
        for (_device_id, name), metric in metrics_by_device_and_name.items()
        if metric["metric_value"] in {"33.33", "10.00"}
    ]
    assert set(access_point_metric_names) == {"packet_loss", "jitter"}


def test_mikrotik_checks_collect_packet_loss_and_jitter(monkeypatch, session_factory):
    with session_factory() as db:
        DeviceRepository(db).upsert_devices(
            [{"name": "Mikrotik Utama", "ip_address": "192.168.1.254", "device_type": "mikrotik"}]
        )

        ping_samples = iter([0.010, 0.015, 0.025])
        monkeypatch.setattr(helpers.settings, "ping_sample_count", 3)
        monkeypatch.setattr(helpers, "safe_ping", lambda _ip_address: next(ping_samples))

        metrics = mikrotik_service.run_mikrotik_checks(db)

    metrics_by_name = {metric["metric_name"]: metric for metric in metrics}
    assert metrics_by_name["ping"]["metric_value"] == "25.00"
    assert metrics_by_name["packet_loss"]["metric_value"] == "0.00"
    assert metrics_by_name["jitter"]["metric_value"] == "7.50"


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    try:
        yield SessionLocal
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
