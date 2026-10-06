"""API contracts for bounded group history, filtering and freshness."""

from datetime import datetime, timedelta

import pytest

from backend.app.services import metric_group_service
from .common import API_HEADERS, _seed_devices_and_metrics, client_context, run

NOW = datetime(2026, 10, 1, 12)


def seed(factory, count=4, metrics=("ping",), samples=4, value="10"):
    devices = [
        dict(name=f"VoIP {i}", ip_address=f"192.0.2.{i + 1}", device_type="voip", site="A" if i % 2 == 0 else "B")
        for i in range(count)
    ]
    return _seed_devices_and_metrics(
        factory,
        devices,
        lambda devices: [
            dict(
                device_id=device.id,
                metric_name=name,
                metric_value=value,
                status="up",
                unit="ms",
                checked_at=NOW - timedelta(seconds=i),
            )
            for device in devices
            for name in metrics
            for i in range(samples)
        ],
    )


def test_group_filters_pages_snapshot_and_device_detail(monkeypatch):
    monkeypatch.setattr(metric_group_service, "now", lambda: NOW)
    with client_context() as (client, factory):
        run(seed(factory))
        first = client.get("/metrics/history/group?group=voip&site=A&device_limit=1", headers=API_HEADERS)
        assert first.status_code == 200
        payload = first.json()
        assert payload["group"]["total_devices"] == 2
        assert payload["group"]["has_more_devices"]
        assert payload["group"]["devices"][0]["freshness"] == "fresh"
        selected_id = payload["group"]["devices"][0]["id"]
        assert {item["device_id"] for item in payload["history"]["items"]} == {selected_id}
        assert {item["device_id"] for item in payload["selected_device_trend"]["items"]} == {selected_id}
        assert {item["device_id"] for item in payload["latest_snapshot"]["items"]} == {selected_id}
        second = client.get(
            "/metrics/history/group?group=voip&site=A&device_limit=1&device_offset=1", headers=API_HEADERS
        ).json()
        assert second["group"]["devices"][0]["id"] != selected_id
        assert not second["group"]["has_more_devices"]
        assert (
            client.get(f"/metrics/history/group?group=voip&device_id={selected_id}", headers=API_HEADERS).json()[
                "group"
            ]["total_devices"]
            == 1
        )
        assert (
            client.get("/metrics/history/group?group=voip&device_type=switch", headers=API_HEADERS).json()["group"][
                "total_devices"
            ]
            == 0
        )
        assert (
            client.get("/metrics/history/group?group=voip&status=down", headers=API_HEADERS).json()[
                "selected_device_trend"
            ]["items"]
            == []
        )
        assert client.get(f"/metrics/history/live?device_id={selected_id}", headers=API_HEADERS).status_code == 200


def test_ruijie_membership_is_case_insensitive_active_and_matches_existing_ui(monkeypatch):
    monkeypatch.setattr(metric_group_service, "now", lambda: NOW)
    with client_context() as (client, factory):
        run(
            _seed_devices_and_metrics(
                factory,
                [
                    dict(name="RUijie AP", ip_address="192.0.2.1", device_type="access_point"),
                    dict(name="Other", ip_address="192.0.2.2", device_type="RUIJIE"),
                    dict(name="Ruijie disabled", ip_address="192.0.2.3", device_type="ruijie", is_active=False),
                    dict(name="Other AP", ip_address="192.0.2.4", device_type="access_point"),
                ],
                lambda devices: [],
            )
        )
        payload = client.get("/metrics/history/group?group=ruijie", headers=API_HEADERS).json()
        assert payload["group"]["total_devices"] == 2
        assert all(item["freshness"] == "no_data" for item in payload["group"]["devices"])
        assert payload["history"]["items"] == []


@pytest.mark.parametrize(
    "query",
    [
        "group=other",
        "group=voip&device_limit=51",
        "group=voip&samples_per_series=201",
        "group=voip&snapshot_limit=101",
        "group=voip&device_offset=-1",
        "group=voip&mode=range",
        "group=voip&mode=range&checked_from=2026-10-02&checked_to=2026-10-01",
        "group=voip&mode=range&checked_from=2026-08-01&checked_to=2026-10-01",
    ],
)
def test_invalid_group_bounds_return_422(query):
    with client_context() as (client, _):
        assert client.get("/metrics/history/group?" + query, headers=API_HEADERS).status_code == 422


def test_range_boundaries_wib_and_stale_data(monkeypatch):
    monkeypatch.setattr(metric_group_service, "now", lambda: NOW + timedelta(days=2))
    with client_context() as (client, factory):
        run(seed(factory, count=1))
        live = client.get("/metrics/history/group?group=voip", headers=API_HEADERS).json()
        assert live["history"]["items"] == []
        assert live["group"]["devices"][0]["freshness"] == "stale"
        query = "/metrics/history/group?group=voip&mode=range&checked_from=2026-10-01T04:59:59Z&checked_to=2026-10-01T05:00:00Z"
        payload = client.get(query, headers=API_HEADERS).json()
        assert payload["group"]["checked_to"] == "2026-10-01T12:00:00"
        assert len(payload["selected_device_trend"]["items"]) == 2
        assert {item["checked_at"] for item in payload["selected_device_trend"]["items"]} == {
            "2026-10-01T11:59:59",
            "2026-10-01T12:00:00",
        }


def test_sampling_and_unicode_payload_are_bounded_and_fair(monkeypatch):
    monkeypatch.setattr(metric_group_service, "now", lambda: NOW)
    with client_context() as (client, factory):
        run(seed(factory, count=20, metrics=tuple(f"metric_{i}" for i in range(9)), samples=20, value="🔥" * 500))
        response = client.get("/metrics/history/group?group=voip&samples_per_series=200", headers=API_HEADERS)
        assert response.status_code == 200
        payload = response.json()
        assert len(response.content) <= payload["group"]["max_payload_bytes"]
        assert len(payload["group"]["series_metric_names"]) == 8
        assert payload["group"]["trend_sampled"]
        assert len(payload["selected_device_trend"]["items"]) <= 2000
        counts: dict[tuple[int, str], int] = {}
        for item in payload["selected_device_trend"]["items"]:
            assert len(item["metric_value"]) <= 256
            key = (item["device_id"], item["metric_name"])
            counts[key] = counts.get(key, 0) + 1
        assert len(counts) == 20 * 8
        assert set(counts.values()) == {payload["group"]["samples_per_series"]}
        assert payload["history"]["meta"]["sampled"]
