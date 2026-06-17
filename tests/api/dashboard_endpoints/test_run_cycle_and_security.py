"""Define test module behavior for `tests/api/dashboard_endpoints/test_run_cycle_and_security.py`.

This module contains automated regression and validation scenarios.
"""

from types import SimpleNamespace

from .common import (
    _seed_devices_and_metrics,
    API_HEADERS,
    Alert,
    client_context,
    DeviceRepository,
    empty_checks,
    Incident,
    MetricRepository,
    run,
    select,
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


def test_stale_active_telegram_event_is_dropped_after_resolve(monkeypatch):
    """Validate stale active Telegram events do not become first-time resolved noise."""
    sent_messages = []

    async def fake_send_telegram_alert(message):
        sent_messages.append(message)

    import backend.app.alerting.engine as engine_module
    from backend.app.repositories.alert_repository import AlertRepository

    monkeypatch.setattr("backend.app.alerting.engine.send_telegram_alert", fake_send_telegram_alert)

    with client_context() as (_client, session_factory):
        async def scenario():
            async with session_factory() as db:
                device = (
                    await DeviceRepository(db).upsert_devices(
                        [
                            {
                                "name": "VoIP - 3",
                                "ip_address": "192.168.88.183",
                                "device_type": "voip",
                                "site": "R. Security",
                            }
                        ]
                    )
                )[0]
                created_at = utcnow() - timedelta(seconds=70)
                alert = Alert(
                    device_id=device.id,
                    alert_type="high_packet_loss_critical",
                    severity="critical",
                    message="VoIP - 3 packet_loss reached 66.67%",
                    status="active",
                    created_at=created_at,
                )
                db.add(alert)
                await db.commit()
                await db.refresh(alert)
                await AlertRepository(db).resolve_alert(alert, utcnow(), commit=True)
                event = {
                    "action": "active",
                    "alert_id": alert.id,
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "message": alert.message,
                    "device": device,
                }
                await engine_module._send_telegram_events(db, AlertRepository(db), [event], commit=True)

        run(scenario())

    assert sent_messages == []


def test_telegram_events_are_ordered_active_before_resolved():
    """Validate mixed Telegram batches present active state before resolved state."""
    import backend.app.alerting.engine as engine_module

    device = SimpleNamespace(id=1, name="AP4", ip_address="192.168.88.52", site="R. Server", device_type="access_point")
    resolved_event = {
        "action": "resolved",
        "alert_id": 1,
        "alert_type": "high_ping_latency_warning",
        "severity": "warning",
        "message": "AP4 ping latency reached 101.10ms",
        "device": device,
    }
    active_event = {
        "action": "active",
        "alert_id": 2,
        "alert_type": "device_down",
        "severity": "critical",
        "message": "AP4 is unreachable",
        "device": device,
    }

    assert engine_module._order_telegram_events([resolved_event, active_event]) == [active_event, resolved_event]


def test_telegram_events_are_deduped_by_alert_state(monkeypatch):
    """Validate duplicate Telegram events are suppressed within one batch."""
    import backend.app.alerting.engine as engine_module

    device = SimpleNamespace(id=1, name="Mikrotik Utama", ip_address="192.168.88.1", site="R. Server", device_type="internet_target")
    event = {
        "action": "resolved",
        "alert_id": 99,
        "alert_type": "high_ping_latency_critical",
        "severity": "critical",
        "message": "Mikrotik Utama ping latency reached 269.37ms",
        "device": device,
    }

    assert engine_module._filter_recent_telegram_events([event, dict(event)]) == [event]
    assert engine_module._filter_recent_telegram_events([event]) == [event]


def test_stale_summary_active_telegram_event_is_dropped_after_resolve(monkeypatch):
    """Validate stale summary-active events are rechecked before send."""
    sent_messages = []

    async def fake_send_telegram_alert(message):
        sent_messages.append(message)

    import backend.app.alerting.engine as engine_module
    from backend.app.repositories.alert_repository import AlertRepository

    monkeypatch.setattr("backend.app.alerting.engine.send_telegram_alert", fake_send_telegram_alert)

    with client_context() as (_client, session_factory):
        async def scenario():
            async with session_factory() as db:
                device = (
                    await DeviceRepository(db).upsert_devices(
                        [
                            {
                                "name": "Core Switch",
                                "ip_address": "192.168.88.2",
                                "device_type": "switch",
                                "site": "R. Server",
                            }
                        ]
                    )
                )[0]
                created_at = utcnow() - timedelta(minutes=30)
                alert = Alert(
                    device_id=device.id,
                    alert_type="high_ping_latency_warning",
                    severity="warning",
                    message="Core Switch ping latency reached 101.10ms",
                    status="active",
                    created_at=created_at,
                )
                db.add(alert)
                await db.commit()
                await db.refresh(alert)
                await AlertRepository(db).resolve_alert(alert, utcnow(), commit=True)
                event = {
                    "action": "summary_active",
                    "alert_id": alert.id,
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "message": alert.message,
                    "device": device,
                }
                await engine_module._send_telegram_events(db, AlertRepository(db), [event], commit=True)

        run(scenario())

    assert sent_messages == []


def test_resolved_event_is_sent_when_sibling_alert_was_recently_notified(monkeypatch):
    """Validate resolved notifications still emit for short-lived duplicate alert rows."""
    sent_messages = []

    async def fake_send_telegram_alert(message):
        sent_messages.append(message)

    import backend.app.alerting.engine as engine_module
    from backend.app.repositories.alert_repository import AlertRepository

    monkeypatch.setattr("backend.app.alerting.engine.send_telegram_alert", fake_send_telegram_alert)
    previous_resolved_window = engine_module.settings.telegram_resolved_correlation_window_seconds
    engine_module.settings.telegram_resolved_correlation_window_seconds = 900

    try:
        with client_context() as (_client, session_factory):
            async def scenario():
                async with session_factory() as db:
                    device = (
                        await DeviceRepository(db).upsert_devices(
                            [
                                {
                                    "name": "Core Switch",
                                    "ip_address": "192.168.88.2",
                                    "device_type": "switch",
                                    "site": "R. Server",
                                }
                            ]
                        )
                    )[0]
                    baseline_created_at = utcnow() - timedelta(minutes=3)
                    baseline = Alert(
                        device_id=device.id,
                        alert_type="high_ping_latency_warning",
                        severity="warning",
                        message="Core Switch ping latency reached 101.10ms",
                        status="active",
                        created_at=baseline_created_at,
                        telegram_notified_at=baseline_created_at + timedelta(seconds=65),
                    )
                    duplicate = Alert(
                        device_id=device.id,
                        alert_type="high_ping_latency_warning",
                        severity="warning",
                        message="Core Switch ping latency reached 99.00ms",
                        status="active",
                        created_at=utcnow() - timedelta(seconds=80),
                    )
                    db.add_all([baseline, duplicate])
                    await db.commit()
                    await db.refresh(duplicate)
                    await AlertRepository(db).resolve_alert(duplicate, utcnow(), commit=True)
                    event = {
                        "action": "resolved",
                        "alert_id": duplicate.id,
                        "alert_type": duplicate.alert_type,
                        "severity": duplicate.severity,
                        "message": duplicate.message,
                        "device": device,
                        "created_at": duplicate.created_at,
                        "resolved_at": utcnow(),
                    }
                    await engine_module._send_telegram_events(db, AlertRepository(db), [event], commit=True)

            run(scenario())
    finally:
        engine_module.settings.telegram_resolved_correlation_window_seconds = previous_resolved_window

    assert sent_messages != []


def test_pending_telegram_events_respect_summary_severity_mode():
    import backend.app.alerting.engine as engine_module

    previous_realtime = engine_module.settings.telegram_realtime_severities
    previous_summary = engine_module.settings.telegram_summary_severities
    previous_summary_interval = engine_module.settings.telegram_summary_interval_seconds
    previous_cooldown = engine_module.settings.telegram_notification_cooldown_seconds
    previous_grace = engine_module.settings.telegram_alert_grace_period_seconds
    engine_module.settings.telegram_realtime_severities = "critical"
    engine_module.settings.telegram_summary_severities = "warning"
    engine_module.settings.telegram_summary_interval_seconds = 300
    engine_module.settings.telegram_notification_cooldown_seconds = 0
    engine_module.settings.telegram_alert_grace_period_seconds = 0
    try:
        device = SimpleNamespace(id=1, name="AP4", ip_address="192.168.88.52", site="R. Server", device_type="access_point")
        alert = Alert(
            id=10,
            device_id=1,
            alert_type="high_ping_latency_warning",
            severity="warning",
            message="AP4 ping latency reached 101.10ms",
            status="active",
            created_at=utcnow() - timedelta(minutes=6),
        )
        events = engine_module._pending_active_telegram_events(
            [alert],
            device_by_id={1: device},
            device_type_by_id={1: "access_point"},
        )
        assert len(events) == 1
        assert events[0]["action"] == "summary_active"
    finally:
        engine_module.settings.telegram_realtime_severities = previous_realtime
        engine_module.settings.telegram_summary_severities = previous_summary
        engine_module.settings.telegram_summary_interval_seconds = previous_summary_interval
        engine_module.settings.telegram_notification_cooldown_seconds = previous_cooldown
        engine_module.settings.telegram_alert_grace_period_seconds = previous_grace


def test_pending_telegram_events_skip_stale_metric_backed_alerts():
    import backend.app.alerting.engine as engine_module

    previous_realtime = engine_module.settings.telegram_realtime_severities
    previous_grace = engine_module.settings.telegram_alert_grace_period_seconds
    previous_interval = engine_module.settings.scheduler_interval_device_seconds
    previous_stale_factor = engine_module.settings.scheduler_job_stale_factor
    engine_module.settings.telegram_realtime_severities = "critical"
    engine_module.settings.telegram_alert_grace_period_seconds = 0
    engine_module.settings.scheduler_interval_device_seconds = 60
    engine_module.settings.scheduler_job_stale_factor = 3
    try:
        device = SimpleNamespace(id=1, name="AP4", ip_address="192.168.88.52", site="R. Server", device_type="access_point")
        alert = Alert(
            id=12,
            device_id=1,
            alert_type="high_ping_latency_critical",
            severity="critical",
            message="AP4 ping latency reached 227.21ms",
            status="active",
            created_at=utcnow() - timedelta(days=2),
        )
        stale_metric = SimpleNamespace(checked_at=utcnow() - timedelta(hours=1))

        events = engine_module._pending_active_telegram_events(
            [alert],
            device_by_id={1: device},
            device_type_by_id={1: "access_point"},
            latest_metrics={(1, "ping"): stale_metric},
        )

        assert events == []
    finally:
        engine_module.settings.telegram_realtime_severities = previous_realtime
        engine_module.settings.telegram_alert_grace_period_seconds = previous_grace
        engine_module.settings.scheduler_interval_device_seconds = previous_interval
        engine_module.settings.scheduler_job_stale_factor = previous_stale_factor


def test_pending_telegram_events_respect_notification_cooldown():
    import backend.app.alerting.engine as engine_module

    previous_realtime = engine_module.settings.telegram_realtime_severities
    previous_summary = engine_module.settings.telegram_summary_severities
    previous_summary_interval = engine_module.settings.telegram_summary_interval_seconds
    previous_cooldown = engine_module.settings.telegram_notification_cooldown_seconds
    previous_grace = engine_module.settings.telegram_alert_grace_period_seconds
    engine_module.settings.telegram_realtime_severities = "critical"
    engine_module.settings.telegram_summary_severities = ""
    engine_module.settings.telegram_summary_interval_seconds = 0
    engine_module.settings.telegram_notification_cooldown_seconds = 900
    engine_module.settings.telegram_alert_grace_period_seconds = 0
    try:
        device = SimpleNamespace(id=1, name="AP4", ip_address="192.168.88.52", site="R. Server", device_type="access_point")
        alert = Alert(
            id=11,
            device_id=1,
            alert_type="device_down",
            severity="critical",
            message="AP4 is unreachable",
            status="active",
            created_at=utcnow() - timedelta(minutes=20),
            telegram_notified_at=utcnow() - timedelta(minutes=5),
        )
        events = engine_module._pending_active_telegram_events(
            [alert],
            device_by_id={1: device},
            device_type_by_id={1: "access_point"},
        )
        assert events == []
    finally:
        engine_module.settings.telegram_realtime_severities = previous_realtime
        engine_module.settings.telegram_summary_severities = previous_summary
        engine_module.settings.telegram_summary_interval_seconds = previous_summary_interval
        engine_module.settings.telegram_notification_cooldown_seconds = previous_cooldown
        engine_module.settings.telegram_alert_grace_period_seconds = previous_grace


def test_alert_evaluation_scopes_active_incident_lookup(monkeypatch):
    from backend.app.alerting.engine import evaluate_alerts
    from backend.app.repositories.incident_repository import IncidentRepository

    scoped_device_ids = []

    async def fail_full_scan(self):
        raise AssertionError("evaluate_alerts should not full-scan active incidents")

    original_scoped_lookup = IncidentRepository.list_active_incidents_by_device_ids

    async def track_scoped_lookup(self, device_ids):
        scoped_device_ids.append(set(device_ids))
        return await original_scoped_lookup(self, device_ids)

    monkeypatch.setattr(IncidentRepository, "list_active_incidents", fail_full_scan)
    monkeypatch.setattr(IncidentRepository, "list_active_incidents_by_device_ids", track_scoped_lookup)

    with client_context() as (_client, session_factory):
        async def scenario():
            async with session_factory() as db:
                device = (
                    await DeviceRepository(db).upsert_devices(
                        [{"name": "Gateway Lokal", "ip_address": "192.168.1.1", "device_type": "internet_target"}]
                    )
                )[0]
                await MetricRepository(db).create_metrics(
                    [
                        {
                            "device_id": device.id,
                            "metric_name": "ping",
                            "metric_value": "timeout",
                            "status": "down",
                            "unit": None,
                            "checked_at": utcnow(),
                        }
                    ]
                )
                notifications = await evaluate_alerts(db)
                return device.id, notifications

        device_id, notifications = run(scenario())

    assert scoped_device_ids == [{device_id}]
    assert [notification["action"] for notification in notifications] == ["created"]


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


def test_alert_evaluation_suppresses_alerts_during_maintenance_window():
    from backend.app.alerting.engine import evaluate_alerts
    from backend.app.models.threshold import MaintenanceWindow

    with client_context() as (_client, session_factory):
        async def scenario():
            async with session_factory() as db:
                devices = await DeviceRepository(db).upsert_devices(
                    [{"name": "Core HQ", "ip_address": "10.0.0.1", "device_type": "internet_target", "site": "HQ"}]
                )
                current_time = utcnow()
                db.add(
                    MaintenanceWindow(
                        name="HQ work",
                        site="HQ",
                        starts_at=current_time - timedelta(minutes=5),
                        ends_at=current_time + timedelta(minutes=30),
                        reason="planned work",
                        is_active=True,
                    )
                )
                await MetricRepository(db).create_metrics(
                    [
                        {
                            "device_id": devices[0].id,
                            "metric_name": "ping",
                            "metric_value": "timeout",
                            "status": "down",
                            "unit": None,
                            "checked_at": current_time,
                        }
                    ],
                    commit=False,
                )
                notifications = await evaluate_alerts(db)
                alerts = await db.scalars(select(Alert))
                incidents = await db.scalars(select(Incident))
                return notifications, list(alerts.all()), list(incidents.all())

        notifications, alerts, incidents = run(scenario())

        assert notifications == []
        assert alerts == []
        assert incidents == []


def test_alert_evaluation_resolves_orphan_duplicate_incidents():
    with client_context() as (_client, session_factory):
        device = run(
            _seed_devices_and_metrics(
                session_factory,
                [{"name": "Mikrotik Utama", "ip_address": "192.168.88.1", "device_type": "mikrotik"}],
                lambda devices: [
                    {
                        "device_id": devices[0].id,
                        "metric_name": "jitter",
                        "metric_value": "0.50",
                        "status": "up",
                        "unit": "ms",
                        "checked_at": utcnow(),
                    }
                ],
            )
        )[0]

        async def scenario():
            from backend.app.alerting.engine import evaluate_alerts

            async with session_factory() as db:
                started_at = utcnow() - timedelta(minutes=5)
                db.add_all(
                    [
                        Incident(
                            device_id=device.id,
                            status="active",
                            summary="Mikrotik Utama jitter reached 88.29ms",
                            started_at=started_at,
                        ),
                        Incident(
                            device_id=device.id,
                            status="active",
                            summary="Mikrotik Utama jitter reached 66.55ms",
                            started_at=started_at,
                        ),
                    ]
                )
                await db.commit()

                notifications = await evaluate_alerts(db)
                incidents = list((await db.scalars(select(Incident))).all())
                return notifications, incidents

        notifications, incidents = run(scenario())

        assert [incident.status for incident in incidents] == ["resolved", "resolved"]
        assert all(incident.ended_at is not None for incident in incidents)
        assert notifications == [
            {
                "action": "resolved",
                "alert_type": None,
                "device_id": device.id,
                "message": "Incident cleared because no active alerts remain",
                "incident_action": "resolved",
            }
        ]

def test_run_cycle_creates_ping_latency_alert():
    with client_context() as (client, session_factory):
        internet_device_id = run(
            _seed_devices_and_metrics(
                session_factory,
                [{"name": "MyRepublic", "ip_address": "8.8.8.8", "device_type": "internet_target"}],
                lambda devices: [
                    {
                        "device_id": devices[0].id,
                        "metric_name": "http_response_time",
                        "metric_value": "1300.00",
                        "status": "up",
                        "unit": "ms",
                        "checked_at": utcnow() - timedelta(seconds=30),
                    },
                ],
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


def test_internet_service_latency_alerts_ignore_single_sample_spikes():
    with client_context() as (_client, session_factory):
        device = run(
            _seed_devices_and_metrics(
                session_factory,
                [{"name": "MyRepublic", "ip_address": "192.168.1.1", "device_type": "internet_target"}],
                lambda devices: [
                    {
                        "device_id": devices[0].id,
                        "metric_name": "dns_resolution_time",
                        "metric_value": "42.00",
                        "status": "up",
                        "unit": "ms",
                        "checked_at": utcnow() - timedelta(seconds=30),
                    },
                    {
                        "device_id": devices[0].id,
                        "metric_name": "http_response_time",
                        "metric_value": "150.00",
                        "status": "up",
                        "unit": "ms",
                        "checked_at": utcnow() - timedelta(seconds=30),
                    },
                    {
                        "device_id": devices[0].id,
                        "metric_name": "dns_resolution_time",
                        "metric_value": "904.03",
                        "status": "up",
                        "unit": "ms",
                        "checked_at": utcnow(),
                    },
                    {
                        "device_id": devices[0].id,
                        "metric_name": "http_response_time",
                        "metric_value": "4531.15",
                        "status": "up",
                        "unit": "ms",
                        "checked_at": utcnow(),
                    },
                ],
            )
        )[0]

        import backend.app.alerting.engine as engine_module

        async def scenario():
            async with session_factory() as db:
                return await engine_module.evaluate_alerts(db)

        notifications = run(scenario())

        assert notifications == []
        assert device.name == "MyRepublic"


def test_internet_service_latency_alerts_require_consecutive_slow_samples():
    with client_context() as (_client, session_factory):
        run(
            _seed_devices_and_metrics(
                session_factory,
                [{"name": "MyRepublic", "ip_address": "192.168.1.1", "device_type": "internet_target"}],
                lambda devices: [
                    {
                        "device_id": devices[0].id,
                        "metric_name": "dns_resolution_time",
                        "metric_value": "711.80",
                        "status": "up",
                        "unit": "ms",
                        "checked_at": utcnow() - timedelta(seconds=30),
                    },
                    {
                        "device_id": devices[0].id,
                        "metric_name": "http_response_time",
                        "metric_value": "4206.93",
                        "status": "up",
                        "unit": "ms",
                        "checked_at": utcnow() - timedelta(seconds=30),
                    },
                    {
                        "device_id": devices[0].id,
                        "metric_name": "dns_resolution_time",
                        "metric_value": "904.03",
                        "status": "up",
                        "unit": "ms",
                        "checked_at": utcnow(),
                    },
                    {
                        "device_id": devices[0].id,
                        "metric_name": "http_response_time",
                        "metric_value": "4531.15",
                        "status": "up",
                        "unit": "ms",
                        "checked_at": utcnow(),
                    },
                ],
            )
        )

        import backend.app.alerting.engine as engine_module

        async def scenario():
            async with session_factory() as db:
                return await engine_module.evaluate_alerts(db)

        notifications = run(scenario())

        assert {notification["alert_type"] for notification in notifications} == {
            "slow_dns_resolution",
            "slow_http_response",
        }


def test_nas_snmp_status_metrics_create_alert_and_incident():
    with client_context() as (client, session_factory):
        run(
            _seed_devices_and_metrics(
                session_factory,
                [{"name": "SSKB_NAS", "ip_address": "192.168.88.111", "device_type": "nas"}],
                lambda devices: [
                    {
                        "device_id": devices[0].id,
                        "metric_name": "ping",
                        "metric_value": "8.00",
                        "status": "up",
                        "unit": "ms",
                        "checked_at": utcnow(),
                    },
                    {
                        "device_id": devices[0].id,
                        "metric_name": "nas_disk:drive_1:status",
                        "metric_value": "crashed",
                        "status": "error",
                        "unit": None,
                        "checked_at": utcnow(),
                    },
                ],
            )
        )

        import backend.app.alerting.engine as engine_module

        async def scenario():
            async with session_factory() as db:
                return await engine_module.evaluate_alerts(db)

        notifications = run(scenario())
        alerts_response = client.get("/alerts/active", headers=API_HEADERS)
        incidents_response = client.get("/incidents?status=active", headers=API_HEADERS)

        assert notifications[0]["alert_type"] == "nas_disk_status_problem"
        assert alerts_response.status_code == 200
        assert alerts_response.json()[0]["alert_type"] == "nas_disk_status_problem"
        assert incidents_response.status_code == 200
        assert len(incidents_response.json()) == 1


def test_nas_stale_dynamic_disk_status_does_not_keep_alert_active():
    with client_context() as (client, session_factory):
        devices = run(
            _seed_devices_and_metrics(
                session_factory,
                [{"name": "NAS - Synology", "ip_address": "192.168.88.111", "device_type": "nas"}],
                lambda seeded_devices: [
                    {
                        "device_id": seeded_devices[0].id,
                        "metric_name": "nas_disk:disk_1:status",
                        "metric_value": "unknown",
                        "status": "warning",
                        "unit": None,
                        "checked_at": utcnow() - timedelta(hours=1),
                    },
                    {
                        "device_id": seeded_devices[0].id,
                        "metric_name": "nas_disk:drive_1:status",
                        "metric_value": "normal",
                        "status": "ok",
                        "unit": None,
                        "checked_at": utcnow(),
                    },
                ],
            )
        )

        async def seed_active_alert():
            async with session_factory() as db:
                db.add(
                    Alert(
                        device_id=devices[0].id,
                        alert_type="nas_disk_status_problem",
                        severity="critical",
                        message="NAS - Synology NAS disk problem: nas_disk:disk_1:status=unknown",
                        status="active",
                        created_at=utcnow() - timedelta(hours=1),
                    )
                )
                await db.commit()

        run(seed_active_alert())

        import backend.app.alerting.engine as engine_module

        async def scenario():
            async with session_factory() as db:
                return await engine_module.evaluate_alerts(db)

        notifications = run(scenario())
        alerts_response = client.get("/alerts/active", headers=API_HEADERS)

        assert notifications[0]["action"] == "resolved"
        assert notifications[0]["alert_type"] == "nas_disk_status_problem"
        assert alerts_response.status_code == 200
        assert alerts_response.json() == []


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
                    "metric_value": "180",
                    "status": "ok",
                    "unit": "count",
                    "checked_at": checked_at,
                },
                {
                    "device_id": mikrotik_device_id,
                    "metric_name": "interface:ether1-wan:rx_mbps",
                    "metric_value": "260.00",
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
    with client_context() as (client, session_factory):
        internet_device_id = run(
            _seed_devices_and_metrics(
                session_factory,
                [{"name": "MyRepublic", "ip_address": "8.8.8.8", "device_type": "internet_target"}],
                lambda devices: [
                    {
                        "device_id": devices[0].id,
                        "metric_name": "http_response_time",
                        "metric_value": "1300.00",
                        "status": "up",
                        "unit": "ms",
                        "checked_at": utcnow() - timedelta(seconds=30),
                    },
                ],
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


def test_run_cycle_uses_switch_specific_quality_thresholds():
    with client_context() as (client, session_factory):
        switch_device_id = run(
            _seed_devices_and_metrics(
                session_factory,
                [{"name": "Switch Core", "ip_address": "192.168.88.20", "device_type": "switch"}],
                [],
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
                    "device_id": switch_device_id,
                    "metric_name": "ping",
                    "metric_value": "55.00",
                    "status": "up",
                    "unit": "ms",
                    "checked_at": now,
                },
                {
                    "device_id": switch_device_id,
                    "metric_name": "packet_loss",
                    "metric_value": "6.00",
                    "status": "warning",
                    "unit": "%",
                    "checked_at": now,
                },
                {
                    "device_id": switch_device_id,
                    "metric_name": "jitter",
                    "metric_value": "25.00",
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

            cycle_response = client.post("/system/run-cycle", headers=API_HEADERS)
            alerts_response = client.get("/alerts/active", headers=API_HEADERS)
        finally:
            run_cycle_module.run_internet_checks = original_internet
            run_cycle_module.run_device_checks = original_device
            run_cycle_module.run_server_checks = original_server
            run_cycle_module.run_mikrotik_checks = original_mikrotik

        assert cycle_response.status_code == 200
        assert cycle_response.json()["alerts_created"] == 3
        assert alerts_response.status_code == 200
        assert {alert["alert_type"] for alert in alerts_response.json()} == {
            "high_ping_latency_warning",
            "high_packet_loss_warning",
            "high_jitter_warning",
        }


def test_run_cycle_keeps_voip_quality_alerts_but_only_telegrams_unreachable(monkeypatch):
    sent_messages = []

    async def fake_send_telegram_alert(message):
        sent_messages.append(message)

    import backend.app.alerting.engine as engine_module

    engine_module._recent_telegram_notification_keys.clear()
    monkeypatch.setattr(engine_module.settings, "telegram_alert_grace_period_seconds", 0)
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
                    "metric_value": "550.00",
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
        assert quality_sent_messages == [
            "\n".join(
                [
                    "[CRITICAL] ALERT ACTIVE",
                    "Device: Dinstar Gateway",
                    "IP: 192.168.88.10",
                    "Site: Office 1",
                    "Type: voip",
                    "Status: ACTIVE",
                    "Alerts:",
                    "- high_packet_loss_critical: Dinstar Gateway packet_loss reached 80.00%",
                ]
            )
        ]

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
        assert sent_messages[0] == quality_sent_messages[0]
        assert sent_messages[1] == "\n".join(
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
        resolved_message_lines = sent_messages[2].splitlines()
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
    sent_messages = []

    async def fake_send_telegram_alert(message):
        sent_messages.append(message)

    import backend.app.alerting.engine as engine_module

    engine_module._recent_telegram_notification_keys.clear()
    monkeypatch.setattr(engine_module.settings, "telegram_alert_grace_period_seconds", 0)
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
                    "metric_value": "timeout" if state["down"] else "900.00",
                    "status": "down" if state["down"] else "up",
                    "unit": None if state["down"] else "ms",
                    "checked_at": now,
                },
                {
                    "device_id": printer_device_id,
                    "metric_name": "jitter",
                    "metric_value": "160.00",
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



