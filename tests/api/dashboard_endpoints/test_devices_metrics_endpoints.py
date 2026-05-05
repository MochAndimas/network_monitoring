"""Define test module behavior for `tests/api/dashboard_endpoints/test_devices_metrics_endpoints.py`.

This module contains automated regression and validation scenarios.
"""

from .common import (
    _seed_devices_and_metrics,
    Alert,
    API_HEADERS,
    client_context,
    date,
    DeviceRepository,
    MetricDailyRollup,
    MetricRepository,
    run,
    select,
    timedelta,
    utcnow,
)

def test_devices_endpoint_returns_latest_status():
    """Validate that devices endpoint returns latest status.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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

def test_create_update_and_delete_device_endpoint():
    """Validate that create update and delete device endpoint.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Validate that device type metadata and validation.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Validate that metrics history filters.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Validate that devices endpoint supports filters and pagination.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
        assert filtered_response.headers.get("deprecation") == "true"
        assert filtered_response.headers.get("x-api-replacement-endpoint") == "/devices/paged"
        assert filtered_response.headers.get("x-api-deprecation-phase") == "announce"
        assert filtered_response.headers.get("x-api-deprecation-removal-on") == "2026-10-31"

        assert paged_response.status_code == 200
        assert len(paged_response.json()) == 1

        paged_meta_response = client.get("/devices/paged?active_only=true&limit=1&offset=0", headers=API_HEADERS)
        assert paged_meta_response.status_code == 200
        paged_payload = paged_meta_response.json()
        assert paged_payload["meta"]["total"] == 2
        assert paged_payload["meta"]["limit"] == 1
        assert len(paged_payload["items"]) == 1

def test_metrics_history_supports_time_window_filters():
    """Validate that metrics history supports time window filters.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
        assert response.headers.get("deprecation") == "true"
        assert response.headers.get("x-api-replacement-endpoint") == "/metrics/history/paged"
        assert response.headers.get("x-api-deprecation-phase") == "announce"
        assert response.headers.get("x-api-deprecation-removal-on") == "2026-10-31"

        paged_response = client.get(
            f"/metrics/history/paged?metric_name=cpu_percent&checked_from={checked_from}&checked_to={checked_to}&limit=10&offset=0",
            headers=API_HEADERS,
        )
        assert paged_response.status_code == 200
        paged_payload = paged_response.json()
        assert paged_payload["meta"]["total"] == 1
        assert len(paged_payload["items"]) == 1

def test_metrics_history_paged_supports_bulk_metric_names_with_per_metric_limit():
    """Validate that metrics history paged supports bulk metric names with per metric limit.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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

def test_metrics_daily_summary_reads_rollup_table_with_filters():
    """Validate that metrics daily summary reads rollup table with filters.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    with client_context() as (client, session_factory):
        async def scenario():
            async with session_factory() as db:
                devices = await DeviceRepository(db).upsert_devices(
                    [
                        {"name": "ISP Utama", "ip_address": "8.8.8.8", "device_type": "internet_target"},
                        {"name": "AP Lobby", "ip_address": "192.168.1.40", "device_type": "access_point"},
                    ]
                )
                db.add_all(
                    [
                        MetricDailyRollup(
                            device_id=devices[0].id,
                            rollup_date=date(2026, 4, 21),
                            total_samples=100,
                            ping_samples=90,
                            down_count=2,
                            uptime_percentage=97.78,
                            average_ping_ms=15.5,
                            min_ping_ms=10.0,
                            max_ping_ms=30.0,
                            average_packet_loss_percent=1.25,
                            average_jitter_ms=3.5,
                            max_jitter_ms=8.0,
                        ),
                        MetricDailyRollup(
                            device_id=devices[1].id,
                            rollup_date=date(2026, 4, 21),
                            total_samples=80,
                            ping_samples=75,
                            down_count=0,
                            uptime_percentage=100.0,
                            average_ping_ms=4.5,
                            min_ping_ms=2.0,
                            max_ping_ms=9.0,
                            average_packet_loss_percent=0.0,
                            average_jitter_ms=1.0,
                            max_jitter_ms=2.0,
                        ),
                    ]
                )
                await db.commit()
                return devices[0].id

        device_id = run(scenario())
        response = client.get(
            f"/metrics/daily-summary?device_id={device_id}&rollup_from=2026-04-20&rollup_to=2026-04-22&limit=50&offset=0",
            headers=API_HEADERS,
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["meta"]["total"] == 1
        assert payload["items"][0]["device_name"] == "ISP Utama"
        assert payload["items"][0]["rollup_date"] == "2026-04-21"
        assert payload["items"][0]["average_ping_ms"] == 15.5
        assert payload["items"][0]["average_packet_loss_percent"] == 1.25

def test_metrics_daily_summary_supports_pagination():
    """Validate that metrics daily summary supports pagination.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    with client_context() as (client, session_factory):
        async def scenario():
            async with session_factory() as db:
                devices = await DeviceRepository(db).upsert_devices(
                    [{"name": "ISP Utama", "ip_address": "8.8.8.8", "device_type": "internet_target"}]
                )
                db.add_all(
                    [
                        MetricDailyRollup(
                            device_id=devices[0].id,
                            rollup_date=date(2026, 4, 22),
                            total_samples=100,
                            ping_samples=90,
                            down_count=2,
                        ),
                        MetricDailyRollup(
                            device_id=devices[0].id,
                            rollup_date=date(2026, 4, 21),
                            total_samples=80,
                            ping_samples=70,
                            down_count=0,
                        ),
                    ]
                )
                await db.commit()

        run(scenario())
        response = client.get("/metrics/daily-summary?limit=1&offset=1", headers=API_HEADERS)

        assert response.status_code == 200
        payload = response.json()
        assert payload["meta"]["total"] == 2
        assert payload["meta"]["limit"] == 1
        assert payload["meta"]["offset"] == 1
        assert len(payload["items"]) == 1
        assert payload["items"][0]["rollup_date"] == "2026-04-21"

def test_latest_snapshot_endpoint_is_unfiltered_and_paged():
    """Validate that latest snapshot endpoint is unfiltered and paged.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Validate that metrics history context endpoint.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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

def test_metrics_history_live_endpoint_returns_lightweight_sample():
    """Validate that metrics history live endpoint returns lightweight sample.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    with client_context() as (client, session_factory):
        async def scenario():
            async with session_factory() as db:
                devices = await DeviceRepository(db).upsert_devices(
                    [{"name": "ISP Utama", "ip_address": "8.8.8.8", "device_type": "internet_target"}]
                )
                current_time = utcnow()
                await MetricRepository(db).create_metrics(
                    [
                        {
                            "device_id": devices[0].id,
                            "metric_name": "ping",
                            "metric_value": "10.00",
                            "status": "up",
                            "unit": "ms",
                            "checked_at": current_time - timedelta(days=2),
                        },
                        {
                            "device_id": devices[0].id,
                            "metric_name": "ping",
                            "metric_value": "12.00",
                            "status": "up",
                            "unit": "ms",
                            "checked_at": current_time - timedelta(minutes=15),
                        },
                        {
                            "device_id": devices[0].id,
                            "metric_name": "packet_loss",
                            "metric_value": "0.00",
                            "status": "ok",
                            "unit": "%",
                            "checked_at": current_time - timedelta(minutes=10),
                        },
                    ]
                )
                return devices[0].id

        device_id = run(scenario())
        response = client.get(
            f"/metrics/history/live?device_id={device_id}&limit=1&selected_device_limit=2&snapshot_limit=10"
            "&checked_from=2000-01-01T00:00:00&checked_to=2099-01-01T00:00:00",
            headers=API_HEADERS,
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["history"]["meta"]["sampled"] is True
        assert payload["history"]["meta"]["total"] == 1
        assert len(payload["history"]["items"]) == 1
        assert len(payload["selected_device_history"]["items"]) == 2
        assert {item["metric_value"] for item in payload["selected_device_history"]["items"]} == {"12.00", "0.00"}
        assert payload["latest_snapshot"]["meta"]["sampled"] is False
        assert len(payload["latest_snapshot"]["items"]) == 2

def test_metrics_history_live_global_snapshot_summary_remains_representative_when_paged():
    """Validate that metrics history live global snapshot summary remains representative when paged.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    with client_context() as (client, session_factory):
        async def scenario():
            async with session_factory() as db:
                devices = await DeviceRepository(db).upsert_devices(
                    [
                        {"name": "ISP A", "ip_address": "8.8.8.8", "device_type": "internet_target"},
                        {"name": "ISP B", "ip_address": "1.1.1.1", "device_type": "internet_target"},
                    ]
                )
                current_time = utcnow()
                await MetricRepository(db).create_metrics(
                    [
                        {
                            "device_id": devices[0].id,
                            "metric_name": "ping",
                            "metric_value": "11.00",
                            "status": "up",
                            "unit": "ms",
                            "checked_at": current_time - timedelta(minutes=5),
                        },
                        {
                            "device_id": devices[1].id,
                            "metric_name": "ping",
                            "metric_value": "timeout",
                            "status": "down",
                            "unit": None,
                            "checked_at": current_time - timedelta(minutes=5),
                        },
                    ]
                )

        run(scenario())
        response = client.get(
            "/metrics/history/live?limit=50&selected_device_limit=50&snapshot_limit=1&snapshot_offset=0",
            headers=API_HEADERS,
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["latest_snapshot"]["meta"]["total"] == 2
        assert payload["latest_snapshot"]["meta"]["sampled"] is True
        assert len(payload["latest_snapshot"]["items"]) == 1
        assert payload["latest_snapshot_status_summary"] == {"down": 1, "up": 1}

def test_latest_snapshot_status_summary_preserves_fallback_first_status_behavior():
    """Validate that latest snapshot status summary preserves fallback first status behavior.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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

def test_threshold_endpoints_and_update():
    """Validate that threshold endpoints and update.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
        assert any(item["key"] == "switch_ping_latency_warning" for item in payload)
        assert any(item["key"] == "switch_ping_latency_critical" for item in payload)
        assert any(item["key"] == "switch_packet_loss_warning" for item in payload)
        assert any(item["key"] == "switch_packet_loss_critical" for item in payload)
        assert any(item["key"] == "switch_jitter_warning" for item in payload)
        assert any(item["key"] == "switch_jitter_critical" for item in payload)
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

