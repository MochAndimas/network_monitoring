"""Define test module behavior for `tests/api/dashboard_endpoints/test_run_cycle_and_security.py`.

This module contains automated regression and validation scenarios.
"""

from types import SimpleNamespace

from .common import (
    _seed_devices_and_metrics,
    API_HEADERS,
    client_context,
    empty_checks,
    run,
    timedelta,
    utcnow,
)


def test_telegram_messages_group_multiple_alerts_for_one_device():
    """Validate Telegram messages are grouped by device and state."""
    from backend.app.alerting.engine import _build_telegram_messages

    device = SimpleNamespace(
        id=1,
        name="MyRepublic - ISP",
        ip_address="192.168.1.1",
        site="R. Server",
        device_type="internet_target",
    )

    messages = _build_telegram_messages(
        [
            {
                "action": "active",
                "alert_type": "high_ping_latency_warning",
                "severity": "warning",
                "message": "MyRepublic - ISP ping latency reached 141.38ms",
                "device": device,
            },
            {
                "action": "active",
                "alert_type": "high_jitter_warning",
                "severity": "warning",
                "message": "MyRepublic - ISP jitter reached 69.73ms",
                "device": device,
            },
        ]
    )

    assert messages == [
        "\n".join(
            [
                "[WARNING] ALERT ACTIVE",
                "Device: MyRepublic - ISP",
                "IP: 192.168.1.1",
                "Site: R. Server",
                "Type: internet_target",
                "Status: ACTIVE",
                "Alerts:",
                "- high_jitter_warning: MyRepublic - ISP jitter reached 69.73ms",
                "- high_ping_latency_warning: MyRepublic - ISP ping latency reached 141.38ms",
            ]
        )
    ]


def test_telegram_resolved_messages_include_alert_duration():
    """Validate resolved Telegram messages include alert duration."""
    from backend.app.alerting.engine import _build_telegram_messages

    device = SimpleNamespace(
        id=1,
        name="MyRepublic - ISP",
        ip_address="192.168.1.1",
        site="R. Server",
        device_type="internet_target",
    )
    resolved_at = utcnow()
    created_at = resolved_at - timedelta(hours=1, minutes=2, seconds=3)

    messages = _build_telegram_messages(
        [
            {
                "action": "resolved",
                "alert_type": "internet_loss",
                "severity": "critical",
                "message": "MyRepublic - ISP is unreachable",
                "device": device,
                "created_at": created_at,
                "resolved_at": resolved_at,
            },
        ]
    )

    assert messages == [
        "\n".join(
            [
                "[CRITICAL] ALERT RESOLVED",
                "Device: MyRepublic - ISP",
                "IP: 192.168.1.1",
                "Site: R. Server",
                "Type: internet_target",
                "Status: RESOLVED",
                "Alerts:",
                "- internet_loss: MyRepublic - ISP is unreachable (duration: 1h 2m)",
            ]
        )
    ]


def test_telegram_events_are_deduped_by_alert_state(monkeypatch):
    """Validate duplicate Telegram events are suppressed briefly."""
    import backend.app.alerting.engine as engine_module

    engine_module._recent_telegram_notification_keys.clear()

    device = SimpleNamespace(id=1, name="Mikrotik Utama", ip_address="192.168.88.1", site="R. Server", device_type="internet_target")
    event = {
        "action": "resolved",
        "alert_id": 99,
        "alert_type": "high_ping_latency_critical",
        "severity": "critical",
        "message": "Mikrotik Utama ping latency reached 269.37ms",
        "device": device,
    }

    try:
        assert engine_module._filter_recent_telegram_events([event, dict(event)]) == [event]
        assert engine_module._filter_recent_telegram_events([event]) == []
    finally:
        engine_module._recent_telegram_notification_keys.clear()


def test_run_cycle_creates_alerts_and_incidents():
    """Validate that run cycle creates alerts and incidents.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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

def test_run_cycle_creates_ping_latency_alert():
    """Validate that run cycle creates ping latency alert.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Validate that run cycle creates mikrotik metric alerts.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Validate that run cycle creates internet quality alerts.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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


def test_run_cycle_keeps_voip_quality_alerts_but_only_telegrams_unreachable(monkeypatch):
    """Validate voip quality alerts stay local and only down alerts send Telegram.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    sent_messages = []

    async def fake_send_telegram_alert(message):
        sent_messages.append(message)

    import backend.app.alerting.engine as engine_module

    engine_module._recent_telegram_notification_keys.clear()
    monkeypatch.setattr("backend.app.alerting.engine.send_telegram_alert", fake_send_telegram_alert)

    with client_context() as (client, session_factory):
        voip_device_id = run(
            _seed_devices_and_metrics(
                session_factory,
                [
                    {
                        "name": "Dinstar Gateway",
                        "ip_address": "192.168.88.10",
                        "device_type": "voip",
                        "site": "Office 1",
                    }
                ],
                [],
            )
        )[0].id

        import backend.app.services.run_cycle_service as run_cycle_module

        original_internet = run_cycle_module.run_internet_checks
        original_device = run_cycle_module.run_device_checks
        original_server = run_cycle_module.run_server_checks
        original_mikrotik = run_cycle_module.run_mikrotik_checks
        state = {"down": False}

        async def fake_device_checks(_db):
            now = utcnow()
            if state["down"]:
                ping_metric = {
                    "device_id": voip_device_id,
                    "metric_name": "ping",
                    "metric_value": "timeout",
                    "status": "down",
                    "unit": None,
                    "checked_at": now,
                }
            else:
                ping_metric = {
                    "device_id": voip_device_id,
                    "metric_name": "ping",
                    "metric_value": "250.00",
                    "status": "up",
                    "unit": "ms",
                    "checked_at": now,
                }
            return [
                ping_metric,
                {
                    "device_id": voip_device_id,
                    "metric_name": "packet_loss",
                    "metric_value": "80.00",
                    "status": "warning",
                    "unit": "%",
                    "checked_at": now,
                },
                {
                    "device_id": voip_device_id,
                    "metric_name": "jitter",
                    "metric_value": "90.00",
                    "status": "warning",
                    "unit": "ms",
                    "checked_at": now,
                },
            ]

        try:
            run_cycle_module.run_internet_checks = empty_checks
            run_cycle_module.run_device_checks = fake_device_checks
            run_cycle_module.run_server_checks = empty_checks
            run_cycle_module.run_mikrotik_checks = empty_checks

            quality_response = client.post("/system/run-cycle", headers=API_HEADERS)
            quality_alerts_response = client.get("/alerts/active", headers=API_HEADERS)
            quality_sent_messages = list(sent_messages)
            state["down"] = True
            down_response = client.post("/system/run-cycle", headers=API_HEADERS)
            down_alerts_response = client.get("/alerts/active", headers=API_HEADERS)
            state["down"] = False
            resolved_response = client.post("/system/run-cycle", headers=API_HEADERS)
        finally:
            run_cycle_module.run_internet_checks = original_internet
            run_cycle_module.run_device_checks = original_device
            run_cycle_module.run_server_checks = original_server
            run_cycle_module.run_mikrotik_checks = original_mikrotik
            engine_module._recent_telegram_notification_keys.clear()

        assert quality_response.status_code == 200
        assert quality_response.json()["alerts_created"] == 3
        assert quality_alerts_response.status_code == 200
        assert {alert["alert_type"] for alert in quality_alerts_response.json()} == {
            "high_ping_latency_critical",
            "high_packet_loss_critical",
            "high_jitter_critical",
        }
        assert quality_sent_messages == []

        assert down_response.status_code == 200
        assert down_response.json()["alerts_created"] == 1
        assert down_alerts_response.status_code == 200
        alert_types = {alert["alert_type"] for alert in down_alerts_response.json()}
        assert alert_types == {
            "device_down",
            "high_packet_loss_critical",
            "high_jitter_critical",
        }
        assert resolved_response.status_code == 200
        assert resolved_response.json()["alerts_resolved"] == 1
        assert sent_messages[0] == "\n".join(
            [
                "[CRITICAL] ALERT ACTIVE",
                "Device: Dinstar Gateway",
                "IP: 192.168.88.10",
                "Site: Office 1",
                "Type: voip",
                "Status: ACTIVE",
                "Alerts:",
                "- device_down: Dinstar Gateway is unreachable",
            ]
        )
        resolved_message_lines = sent_messages[1].splitlines()
        assert resolved_message_lines[:7] == [
            "[CRITICAL] ALERT RESOLVED",
            "Device: Dinstar Gateway",
            "IP: 192.168.88.10",
            "Site: Office 1",
            "Type: voip",
            "Status: RESOLVED",
            "Alerts:",
        ]
        assert resolved_message_lines[7].startswith("- device_down: Dinstar Gateway is unreachable (duration: ")


def test_run_cycle_creates_printer_alerts_and_incident():
    """Validate that run cycle creates printer alerts and incident.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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


def test_run_cycle_keeps_printer_quality_alerts_but_filters_telegram(monkeypatch):
    """Validate printer quality alerts stay local while Telegram is filtered.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    sent_messages = []

    async def fake_send_telegram_alert(message):
        sent_messages.append(message)

    import backend.app.alerting.engine as engine_module

    engine_module._recent_telegram_notification_keys.clear()
    monkeypatch.setattr("backend.app.alerting.engine.send_telegram_alert", fake_send_telegram_alert)

    with client_context() as (client, session_factory):
        printer_device_id = run(
            _seed_devices_and_metrics(
                session_factory,
                [
                    {
                        "name": "EPSON L3250 - 1",
                        "ip_address": "192.168.88.38",
                        "device_type": "printer",
                        "site": "Finance",
                    }
                ],
                [],
            )
        )[0].id

        import backend.app.services.run_cycle_service as run_cycle_module

        original_internet = run_cycle_module.run_internet_checks
        original_device = run_cycle_module.run_device_checks
        original_server = run_cycle_module.run_server_checks
        original_mikrotik = run_cycle_module.run_mikrotik_checks
        state = {"down": False}

        async def fake_device_checks(_db):
            now = utcnow()
            return [
                {
                    "device_id": printer_device_id,
                    "metric_name": "ping",
                    "metric_value": "timeout" if state["down"] else "250.00",
                    "status": "down" if state["down"] else "up",
                    "unit": None if state["down"] else "ms",
                    "checked_at": now,
                },
                {
                    "device_id": printer_device_id,
                    "metric_name": "jitter",
                    "metric_value": "90.00",
                    "status": "warning",
                    "unit": "ms",
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
            ]

        try:
            run_cycle_module.run_internet_checks = empty_checks
            run_cycle_module.run_device_checks = fake_device_checks
            run_cycle_module.run_server_checks = empty_checks
            run_cycle_module.run_mikrotik_checks = empty_checks

            quality_response = client.post("/system/run-cycle", headers=API_HEADERS)
            quality_alerts_response = client.get("/alerts/active", headers=API_HEADERS)
            quality_sent_messages = list(sent_messages)
            state["down"] = True
            down_response = client.post("/system/run-cycle", headers=API_HEADERS)
            down_alerts_response = client.get("/alerts/active", headers=API_HEADERS)
            state["down"] = False
            resolved_response = client.post("/system/run-cycle", headers=API_HEADERS)
        finally:
            run_cycle_module.run_internet_checks = original_internet
            run_cycle_module.run_device_checks = original_device
            run_cycle_module.run_server_checks = original_server
            run_cycle_module.run_mikrotik_checks = original_mikrotik
            engine_module._recent_telegram_notification_keys.clear()

        assert quality_response.status_code == 200
        assert quality_response.json()["alerts_created"] == 3
        assert quality_alerts_response.status_code == 200
        assert {alert["alert_type"] for alert in quality_alerts_response.json()} == {
            "high_ping_latency_critical",
            "high_jitter_critical",
            "printer_error_state",
        }
        assert quality_sent_messages == [
            "\n".join(
                [
                    "[CRITICAL] ALERT ACTIVE",
                    "Device: EPSON L3250 - 1",
                    "IP: 192.168.88.38",
                    "Site: Finance",
                    "Type: printer",
                    "Status: ACTIVE",
                    "Alerts:",
                    "- printer_error_state: EPSON L3250 - 1 printer error state: jammed",
                ]
            )
        ]

        assert down_response.status_code == 200
        assert down_response.json()["alerts_created"] == 1
        assert down_alerts_response.status_code == 200
        alert_types = {alert["alert_type"] for alert in down_alerts_response.json()}
        assert alert_types == {
            "device_down",
            "high_jitter_critical",
            "printer_error_state",
        }
        assert sent_messages[:2] == [
            "\n".join(
                [
                    "[CRITICAL] ALERT ACTIVE",
                    "Device: EPSON L3250 - 1",
                    "IP: 192.168.88.38",
                    "Site: Finance",
                    "Type: printer",
                    "Status: ACTIVE",
                    "Alerts:",
                    "- printer_error_state: EPSON L3250 - 1 printer error state: jammed",
                ]
            ),
            "\n".join(
                [
                    "[CRITICAL] ALERT ACTIVE",
                    "Device: EPSON L3250 - 1",
                    "IP: 192.168.88.38",
                    "Site: Finance",
                    "Type: printer",
                    "Status: ACTIVE",
                    "Alerts:",
                    "- device_down: EPSON L3250 - 1 is unreachable",
                ]
            ),
        ]
        resolved_message_lines = sent_messages[2].splitlines()
        assert resolved_message_lines[:7] == [
            "[CRITICAL] ALERT RESOLVED",
            "Device: EPSON L3250 - 1",
            "IP: 192.168.88.38",
            "Site: Finance",
            "Type: printer",
            "Status: RESOLVED",
            "Alerts:",
        ]
        assert resolved_message_lines[7].startswith("- device_down: EPSON L3250 - 1 is unreachable (duration: ")
        assert resolved_response.status_code == 200
        assert resolved_response.json()["alerts_resolved"] == 1


def test_internal_api_key_protects_mutation_endpoints():
    """Validate that internal api key protects mutation endpoints.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Validate that internal api key scopes split write and ops access.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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
    """Validate that internal api key protects read endpoints.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    with client_context() as (client, _session_factory):
        unauthorized_devices = client.get("/devices")
        authorized_devices = client.get("/devices", headers=API_HEADERS)

        assert unauthorized_devices.status_code == 401
        assert authorized_devices.status_code == 200

def test_missing_credentials_are_rejected_without_api_key_or_bearer_token():
    """Validate that missing credentials are rejected without api key or bearer token.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
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

