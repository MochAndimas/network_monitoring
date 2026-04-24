"""Split tests from legacy test_dashboard_endpoints module."""

from .common import *  # noqa: F401,F403

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

def test_alerts_and_incidents_paged_endpoints_include_meta_and_keep_legacy_contracts():
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
                db.add_all(
                    [
                        Alert(
                            device_id=devices[0].id,
                            alert_type="internet_loss",
                            severity="critical",
                            message="gateway down",
                            status="active",
                            created_at=now - timedelta(minutes=3),
                        ),
                        Alert(
                            device_id=devices[1].id,
                            alert_type="high_cpu",
                            severity="warning",
                            message="cpu high",
                            status="active",
                            created_at=now - timedelta(minutes=2),
                        ),
                        Alert(
                            device_id=devices[1].id,
                            alert_type="disk_space",
                            severity="high",
                            message="disk almost full",
                            status="active",
                            created_at=now - timedelta(minutes=1),
                        ),
                        Alert(
                            device_id=devices[1].id,
                            alert_type="internet_loss",
                            severity="critical",
                            message="resolved sample",
                            status="resolved",
                            created_at=now - timedelta(minutes=10),
                        ),
                    ]
                )
                db.add_all(
                    [
                        Incident(
                            device_id=devices[0].id,
                            status="active",
                            summary="gateway outage",
                            started_at=now - timedelta(minutes=5),
                        ),
                        Incident(
                            device_id=devices[1].id,
                            status="active",
                            summary="cpu saturation",
                            started_at=now - timedelta(minutes=4),
                        ),
                        Incident(
                            device_id=devices[1].id,
                            status="resolved",
                            summary="historical outage",
                            started_at=now - timedelta(minutes=20),
                            ended_at=now - timedelta(minutes=10),
                        ),
                    ]
                )
                await db.commit()

        run(scenario())

        legacy_alerts = client.get("/alerts/active?limit=2&offset=1", headers=API_HEADERS)
        paged_alerts = client.get("/alerts/active/paged?limit=2&offset=1", headers=API_HEADERS)
        paged_alerts_filtered = client.get(
            "/alerts/active/paged?limit=10&offset=0&severity=critical&search=gateway",
            headers=API_HEADERS,
        )
        legacy_incidents = client.get("/incidents?status=active&limit=1&offset=0", headers=API_HEADERS)
        paged_incidents = client.get("/incidents/paged?status=active&limit=1&offset=0", headers=API_HEADERS)
        paged_incidents_filtered = client.get(
            "/incidents/paged?status=active&limit=10&offset=0&search=cpu",
            headers=API_HEADERS,
        )

        assert legacy_alerts.status_code == 200
        assert len(legacy_alerts.json()) == 2
        assert legacy_alerts.headers.get("deprecation") == "true"
        assert legacy_alerts.headers.get("x-api-replacement-endpoint") == "/alerts/active/paged"
        assert legacy_alerts.headers.get("x-api-deprecation-phase") == "announce"
        assert legacy_alerts.headers.get("x-api-deprecation-removal-on") == "2026-10-31"

        assert paged_alerts.status_code == 200
        paged_alert_payload = paged_alerts.json()
        assert paged_alert_payload["meta"] == {"total": 3, "limit": 2, "offset": 1}
        assert len(paged_alert_payload["items"]) == 2
        assert paged_alert_payload["items"][0]["alert_type"] == "high_cpu"
        assert paged_alerts_filtered.status_code == 200
        filtered_alert_payload = paged_alerts_filtered.json()
        assert filtered_alert_payload["meta"] == {"total": 1, "limit": 10, "offset": 0}
        assert len(filtered_alert_payload["items"]) == 1
        assert filtered_alert_payload["items"][0]["severity"] == "critical"
        assert filtered_alert_payload["items"][0]["message"] == "gateway down"

        assert legacy_incidents.status_code == 200
        assert len(legacy_incidents.json()) == 1
        assert legacy_incidents.headers.get("deprecation") == "true"
        assert legacy_incidents.headers.get("x-api-replacement-endpoint") == "/incidents/paged"
        assert legacy_incidents.headers.get("x-api-deprecation-phase") == "announce"
        assert legacy_incidents.headers.get("x-api-deprecation-removal-on") == "2026-10-31"

        assert paged_incidents.status_code == 200
        paged_incident_payload = paged_incidents.json()
        assert paged_incident_payload["meta"] == {"total": 2, "limit": 1, "offset": 0}
        assert len(paged_incident_payload["items"]) == 1
        assert paged_incident_payload["items"][0]["status"] == "active"
        assert paged_incidents_filtered.status_code == 200
        filtered_incident_payload = paged_incidents_filtered.json()
        assert filtered_incident_payload["meta"] == {"total": 1, "limit": 10, "offset": 0}
        assert len(filtered_incident_payload["items"]) == 1
        assert filtered_incident_payload["items"][0]["summary"] == "cpu saturation"

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

