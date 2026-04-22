import asyncio
from datetime import timedelta

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


def test_internet_checks_anchor_dns_http_and_public_ip_to_preferred_isp(monkeypatch, session_factory):
    ping_samples = iter([0.010, 0.010, 0.010, 0.010, 0.010, 0.010])
    monkeypatch.setattr(helpers.settings, "ping_sample_count", 3)

    async def fake_safe_ping(_ip_address):
        return next(ping_samples)

    monkeypatch.setattr(helpers, "safe_ping", fake_safe_ping)

    class FakeLoop:
        async def getaddrinfo(self, *_args, **_kwargs):
            return [object()]

    monkeypatch.setattr(internet_service.asyncio, "get_running_loop", lambda: FakeLoop())

    async def fake_client_get(self, url, **_kwargs):
        request = httpx.Request("GET", url)
        if url == internet_service.settings.public_ip_check_url:
            return httpx.Response(200, request=request, text="203.0.113.20")
        return httpx.Response(204, request=request)

    monkeypatch.setattr(internet_service.httpx.AsyncClient, "get", fake_client_get)

    async def scenario():
        async with session_factory() as db:
            devices = await DeviceRepository(db).upsert_devices(
                [
                    {"name": "Mikrotik Utama", "ip_address": "192.168.1.254", "device_type": "internet_target"},
                    {"name": "MyRepublic - ISP", "ip_address": "8.8.8.8", "device_type": "internet_target"},
                ]
            )
            metrics = await internet_service.run_internet_checks(db)
            isp_device = next(device for device in devices if device.name == "MyRepublic - ISP")
            mikrotik_device = next(device for device in devices if device.name == "Mikrotik Utama")
            return metrics, isp_device.id, mikrotik_device.id

    metrics, isp_device_id, mikrotik_device_id = run(scenario())

    dns_owner_ids = {metric["device_id"] for metric in metrics if metric["metric_name"] == "dns_resolution_time"}
    http_owner_ids = {metric["device_id"] for metric in metrics if metric["metric_name"] == "http_response_time"}
    public_ip_owner_ids = {metric["device_id"] for metric in metrics if metric["metric_name"] == "public_ip"}

    assert dns_owner_ids == {isp_device_id}
    assert http_owner_ids == {isp_device_id}
    assert public_ip_owner_ids == {isp_device_id}
    assert mikrotik_device_id not in dns_owner_ids | http_owner_ids | public_ip_owner_ids


def test_access_point_and_printer_checks_collect_packet_loss_jitter_and_snmp(monkeypatch, session_factory):
    ping_samples = iter([0.010, None, 0.020, 0.030, 0.030, 0.030])
    monkeypatch.setattr(helpers.settings, "ping_sample_count", 3)

    async def fake_safe_ping(_ip_address):
        return next(ping_samples)

    monkeypatch.setattr(helpers, "safe_ping", fake_safe_ping)

    async def fake_collect_printer_snmp_metrics(device_id, _ip_address):
        checked_at = utcnow()
        return [
            {
                "device_id": device_id,
                "metric_name": "printer_uptime_seconds",
                "metric_value": "7200",
                "status": "ok",
                "unit": "s",
                "checked_at": checked_at,
            },
            {
                "device_id": device_id,
                "metric_name": "printer_status",
                "metric_value": "idle",
                "status": "up",
                "unit": None,
                "checked_at": checked_at,
            },
            {
                "device_id": device_id,
                "metric_name": "printer_ink_status",
                "metric_value": "ok",
                "status": "ok",
                "unit": None,
                "checked_at": checked_at,
            },
            {
                "device_id": device_id,
                "metric_name": "printer_error_state",
                "metric_value": "none",
                "status": "ok",
                "unit": None,
                "checked_at": checked_at,
            },
            {
                "device_id": device_id,
                "metric_name": "printer_paper_status",
                "metric_value": "ok",
                "status": "ok",
                "unit": None,
                "checked_at": checked_at,
            },
            {
                "device_id": device_id,
                "metric_name": "printer_total_pages",
                "metric_value": "1234",
                "status": "ok",
                "unit": "pages",
                "checked_at": checked_at,
            },
        ]

    monkeypatch.setattr(device_service, "collect_printer_snmp_metrics", fake_collect_printer_snmp_metrics)

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
    assert metrics_by_device_and_name[(printer_id, "printer_status")]["metric_value"] == "idle"
    assert metrics_by_device_and_name[(printer_id, "printer_ink_status")]["metric_value"] == "ok"
    assert metrics_by_device_and_name[(printer_id, "printer_total_pages")]["metric_value"] == "1234"


def test_voip_checks_collect_ping_packet_loss_and_jitter(monkeypatch, session_factory):
    ping_samples = iter([0.012, 0.018, None])
    monkeypatch.setattr(helpers.settings, "ping_sample_count", 3)

    async def fake_safe_ping(_ip_address):
        return next(ping_samples)

    monkeypatch.setattr(helpers, "safe_ping", fake_safe_ping)

    async def scenario():
        async with session_factory() as db:
            await DeviceRepository(db).upsert_devices(
                [{"name": "Dinstar Gateway", "ip_address": "192.168.88.10", "device_type": "voip"}]
            )
            return await device_service.run_device_checks(db)

    metrics = run(scenario())

    metrics_by_name = {metric["metric_name"]: metric for metric in metrics}
    assert metrics_by_name["ping"]["metric_value"] == "18.00"
    assert metrics_by_name["packet_loss"]["metric_value"] == "33.33"
    assert metrics_by_name["packet_loss"]["status"] == "warning"
    assert metrics_by_name["jitter"]["metric_value"] == "6.00"


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


def test_mikrotik_api_checks_collect_routeros_metrics(monkeypatch, session_factory):
    ping_samples = iter([0.010, 0.010, 0.010])
    monkeypatch.setattr(helpers.settings, "ping_sample_count", 3)

    async def fake_safe_ping(_ip_address):
        return next(ping_samples)

    class FakeApi:
        def path(self, *parts):
            paths = {
                ("system", "resource"): [
                    {
                        "cpu-load": "12",
                        "total-memory": "1000",
                        "free-memory": "250",
                        "total-hdd-space": "2000",
                        "free-hdd-space": "500",
                    }
                ],
                ("interface",): [
                    {"name": "ether1", "running": True, "rx-byte": "1001000", "tx-byte": "2002000"}
                ],
                ("ip", "dhcp-server", "lease"): [
                    {"status": "bound", "active-address": "192.168.88.10", "mac-address": "AA:BB:CC:DD:EE:01"}
                ],
                ("ip", "arp"): [
                    {"address": "192.168.88.10", "mac-address": "AA:BB:CC:DD:EE:01"},
                    {"address": "192.168.88.11", "mac-address": "AA:BB:CC:DD:EE:02"},
                ],
                ("ip", "firewall", "filter"): [
                    {"chain": "forward", "action": "drop", "comment": "bad", "packets": "5000", "bytes": "10000000"}
                ],
                ("ip", "firewall", "nat"): [],
                ("queue", "simple"): [
                    {"name": "user-a", "bytes": "3003000/4004000", "rate": "7000000/8000000"}
                ],
            }
            return paths.get(parts, [])

        def close(self):
            return None

    monkeypatch.setattr(helpers, "safe_ping", fake_safe_ping)
    monkeypatch.setattr(mikrotik_service.settings, "mikrotik_host", "192.168.88.1")
    monkeypatch.setattr(mikrotik_service.settings, "mikrotik_username", "monitor")
    monkeypatch.setattr(mikrotik_service.settings, "mikrotik_password", "secret")
    monkeypatch.setattr(mikrotik_service, "connect", lambda **_kwargs: FakeApi())

    async def scenario():
        async with session_factory() as db:
            devices = await DeviceRepository(db).upsert_devices(
                [{"name": "Mikrotik Utama", "ip_address": "192.168.88.1", "device_type": "internet_target"}]
            )
            device_id = devices[0].id
            previous_checked_at = utcnow() - timedelta(seconds=1)
            await MetricRepository(db).create_metrics(
                [
                    {
                        "device_id": device_id,
                        "metric_name": "interface:ether1:rx_bytes",
                        "metric_value": "1000",
                        "status": "up",
                        "unit": "bytes",
                        "checked_at": previous_checked_at,
                    },
                    {
                        "device_id": device_id,
                        "metric_name": "firewall:filter:001_forward_drop_bad:packets",
                        "metric_value": "0",
                        "status": "ok",
                        "unit": "packets",
                        "checked_at": previous_checked_at,
                    },
                ]
            )
            return await mikrotik_service.run_mikrotik_checks(db)

    metrics = run(scenario())
    metrics_by_name = {metric["metric_name"]: metric for metric in metrics}

    assert metrics_by_name["mikrotik_api"]["metric_value"] == "ok"
    assert metrics_by_name["mikrotik_api"]["status"] == "ok"
    assert metrics_by_name["cpu_percent"]["metric_value"] == "12"
    assert metrics_by_name["memory_percent"]["metric_value"] == "75.00"
    assert metrics_by_name["disk_percent"]["metric_value"] == "75.00"
    assert metrics_by_name["dhcp_active_leases"]["metric_value"] == "1"
    assert metrics_by_name["connected_clients"]["metric_value"] == "2"
    assert float(metrics_by_name["interface:ether1:rx_mbps"]["metric_value"]) > 0
    assert metrics_by_name["queue:user-a:rx_mbps"]["metric_value"] == "7.00"
    assert metrics_by_name["queue:user-a:tx_mbps"]["metric_value"] == "8.00"
    assert metrics_by_name["firewall:filter:001_forward_drop_bad:pps"]["status"] == "warning"


def test_mikrotik_dynamic_metric_controls_support_section_toggle_limits_and_allowlist(monkeypatch, session_factory):
    ping_samples = iter([0.010, 0.010, 0.010])
    monkeypatch.setattr(helpers.settings, "ping_sample_count", 3)

    async def fake_safe_ping(_ip_address):
        return next(ping_samples)

    class FakeApi:
        def path(self, *parts):
            paths = {
                ("system", "resource"): [
                    {
                        "cpu-load": "12",
                        "total-memory": "1000",
                        "free-memory": "250",
                        "total-hdd-space": "2000",
                        "free-hdd-space": "500",
                    }
                ],
                ("interface",): [
                    {"name": "ether1", "running": True, "rx-byte": "1001000", "tx-byte": "2002000"},
                    {"name": "ether2", "running": True, "rx-byte": "1001000", "tx-byte": "2002000"},
                ],
                ("ip", "dhcp-server", "lease"): [],
                ("ip", "arp"): [],
                ("ip", "firewall", "filter"): [
                    {"chain": "forward", "action": "drop", "comment": "bad", "packets": "5000", "bytes": "10000000"}
                ],
                ("ip", "firewall", "nat"): [
                    {"chain": "srcnat", "action": "masquerade", "comment": "wan", "packets": "100", "bytes": "1200"}
                ],
                ("queue", "simple"): [
                    {"name": "user-a", "bytes": "3003000/4004000", "rate": "7000000/8000000"},
                    {"name": "user-b", "bytes": "1000/1000", "rate": "1000/1000"},
                ],
            }
            return paths.get(parts, [])

        def close(self):
            return None

    monkeypatch.setattr(helpers, "safe_ping", fake_safe_ping)
    monkeypatch.setattr(mikrotik_service.settings, "mikrotik_host", "192.168.88.1")
    monkeypatch.setattr(mikrotik_service.settings, "mikrotik_username", "monitor")
    monkeypatch.setattr(mikrotik_service.settings, "mikrotik_password", "secret")
    monkeypatch.setattr(mikrotik_service.settings, "mikrotik_dynamic_sections", "interface,queue")
    monkeypatch.setattr(mikrotik_service.settings, "mikrotik_dynamic_interface_allowlist", "ether1")
    monkeypatch.setattr(mikrotik_service.settings, "mikrotik_dynamic_queue_allowlist", "user-a")
    monkeypatch.setattr(mikrotik_service.settings, "mikrotik_dynamic_max_interfaces", 1)
    monkeypatch.setattr(mikrotik_service.settings, "mikrotik_dynamic_max_queues", 1)
    monkeypatch.setattr(mikrotik_service.settings, "mikrotik_dynamic_max_firewall_rules", 1)
    monkeypatch.setattr(mikrotik_service, "connect", lambda **_kwargs: FakeApi())

    async def scenario():
        async with session_factory() as db:
            devices = await DeviceRepository(db).upsert_devices(
                [{"name": "Mikrotik Utama", "ip_address": "192.168.88.1", "device_type": "internet_target"}]
            )
            return await mikrotik_service.run_mikrotik_checks(db), devices[0].id

    metrics, device_id = run(scenario())

    metric_names = {metric["metric_name"] for metric in metrics if metric["device_id"] == device_id}
    assert "interface:ether1:rx_mbps" in metric_names
    assert "queue:user-a:rx_mbps" in metric_names
    assert not any(name.startswith("interface:ether2:") for name in metric_names)
    assert not any(name.startswith("queue:user-b:") for name in metric_names)
    assert not any(name.startswith("firewall:") for name in metric_names)


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
