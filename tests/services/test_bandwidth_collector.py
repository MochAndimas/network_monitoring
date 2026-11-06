"""Snapshots reuse existing API reads and are emitted only after complete success."""

from backend.app.models.device import Device
from backend.app.monitors.mikrotik.parts import impl
from tests.test_utils import run


def test_snapshot_reuses_dhcp_and_arp_fetches(monkeypatch):
    calls = []

    class API:
        def path(self, *parts):
            calls.append(parts)
            if parts == ("ip", "dhcp-server", "lease"):
                return [
                    {
                        "address": "192.168.1.31",
                        "mac-address": "70:08:94:1B:9C:DF",
                        "host-name": "laptop",
                        "status": "bound",
                    }
                ]
            return []

        def close(self):
            pass

    monkeypatch.setattr(impl, "connect", lambda **kwargs: API())
    monkeypatch.setattr(impl.settings, "mikrotik_dynamic_sections", "")
    snapshots = []
    result = run(
        impl._collect_mikrotik_api_metrics(
            Device(id=42, name="router", ip_address="192.0.2.1", device_type="mikrotik"),
            impl.settings.mikrotik,
            {},
            snapshots=snapshots,
        )
    )
    assert len(snapshots) == 1
    assert snapshots[0].router_id == 42
    assert snapshots[0].clients[0].hostname == "laptop"
    assert calls.count(("ip", "dhcp-server", "lease")) == 1
    assert calls.count(("ip", "arp")) == 1
    assert next(item for item in result if item["metric_name"] == "mikrotik_api")["status"] == "ok"


def test_partial_api_failure_never_becomes_an_empty_inventory_snapshot(monkeypatch):
    class API:
        def path(self, *parts):
            if parts == ("ip", "arp"):
                raise TimeoutError("timed out")
            return []

        def close(self):
            pass

    monkeypatch.setattr(impl, "connect", lambda **kwargs: API())
    snapshots = []
    result = run(
        impl._collect_mikrotik_api_metrics(
            Device(id=42, name="router", ip_address="192.0.2.1", device_type="mikrotik"),
            impl.settings.mikrotik,
            {},
            snapshots=snapshots,
        )
    )
    assert snapshots == []
    assert result[-1]["metric_value"] == "timeout"
