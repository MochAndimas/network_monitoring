"""Define test module behavior for `tests/api/dashboard_endpoints/test_auth_endpoints.py`.

This module contains automated regression and validation scenarios.
"""

from .common import *  # noqa: F401,F403

def test_auth_login_me_and_logout_flow():
    """Validate that auth login me and logout flow.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    with client_context() as (client, session_factory):
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))

        login_response = client.post(
            "/auth/login",
            json={"username": "viewer", "password": "StrongPass123!", "remember": True},
        )

        assert login_response.status_code == 200
        payload = login_response.json()
        token = payload["access_token"]
        assert token.count(".") == 2
        assert payload["user"]["role"] == "viewer"
        assert login_response.cookies.get("network_monitoring_session") == token
        assert login_response.cookies.get("network_monitoring_refresh") is not None

        restore_response = client.post("/auth/restore")
        assert restore_response.status_code == 200
        restored_token = restore_response.json()["access_token"]
        assert restored_token.count(".") == 2
        assert restored_token != ""
        assert restored_token != token

        me_response = client.get("/auth/me", headers={"authorization": f"Bearer {token}"})
        assert me_response.status_code == 200
        assert me_response.json()["username"] == "viewer"

        me_with_cookie = client.get("/auth/me")
        assert me_with_cookie.status_code == 200
        assert me_with_cookie.json()["username"] == "viewer"

        sessions_with_cookie = client.get("/auth/sessions")
        assert sessions_with_cookie.status_code == 401

        protected_with_cookie = client.get("/devices")
        assert protected_with_cookie.status_code == 401

        logout_response = client.post("/auth/logout", headers={"authorization": f"Bearer {token}"})
        assert logout_response.status_code == 200
        assert client.cookies.get("network_monitoring_session") is None
        assert client.cookies.get("network_monitoring_refresh") is None

        me_after_logout = client.get("/auth/me", headers={"authorization": f"Bearer {token}"})
        assert me_after_logout.status_code == 401
        restore_after_logout = client.post("/auth/restore")
        assert restore_after_logout.status_code == 401

def test_auth_me_prefers_bearer_token_over_cookie_session():
    """Validate that auth me prefers bearer token over cookie session.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    with client_context() as (client_a, session_factory):
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer", full_name="Viewer User"))
        run(_create_user(session_factory, username="adminuser", password="StrongPass123!", role="admin", full_name="Admin User"))

        viewer_login = client_a.post("/auth/login", json={"username": "viewer", "password": "StrongPass123!"})
        assert viewer_login.status_code == 200

        with TestClient(app) as client_b:
            admin_login = client_b.post("/auth/login", json={"username": "adminuser", "password": "StrongPass123!"})
            assert admin_login.status_code == 200

            mixed_me_response = client_a.get(
                "/auth/me",
                headers={"authorization": f"Bearer {admin_login.json()['access_token']}"},
            )

        assert mixed_me_response.status_code == 200
        assert mixed_me_response.json()["username"] == "adminuser"

def test_auth_requires_dedicated_password_and_jwt_secrets():
    """Validate that auth requires dedicated password and jwt secrets.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    import backend.app.core.security as security_module

    original_password_secret = security_module.settings.auth_password_secret
    original_jwt_secret = security_module.settings.auth_jwt_secret
    original_api_key = security_module.settings.internal_api_key
    original_bootstrap_password = security_module.settings.bootstrap_admin_password

    security_module.settings.auth_password_secret = ""
    security_module.settings.auth_jwt_secret = ""
    security_module.settings.internal_api_key = "legacy-api-key"
    security_module.settings.bootstrap_admin_password = "legacy-bootstrap-password"

    try:
        try:
            validate_auth_configuration()
            assert False, "validate_auth_configuration should fail when dedicated auth secrets are missing"
        except AuthConfigurationError as exc:
            assert "AUTH_PASSWORD_SECRET" in str(exc) or "AUTH_JWT_SECRET" in str(exc)
    finally:
        security_module.settings.auth_password_secret = original_password_secret
        security_module.settings.auth_jwt_secret = original_jwt_secret
        security_module.settings.internal_api_key = original_api_key
        security_module.settings.bootstrap_admin_password = original_bootstrap_password

def test_production_auth_validation_rejects_insecure_defaults():
    """Validate that production auth validation rejects insecure defaults.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    import backend.app.core.security as security_module

    original_app_env = security_module.settings.app_env
    original_password_secret = security_module.settings.auth_password_secret
    original_jwt_secret = security_module.settings.auth_jwt_secret
    original_internal_api_key = security_module.settings.internal_api_key
    original_cookie_secure = security_module.settings.auth_cookie_secure
    original_trusted_hosts = security_module.settings.trusted_hosts
    original_cors_origins = security_module.settings.cors_origins
    original_allow_insecure = security_module.settings.allow_insecure_no_auth

    security_module.settings.app_env = "production"
    security_module.settings.auth_password_secret = "test-password-secret"
    security_module.settings.auth_jwt_secret = "test-jwt-secret"
    security_module.settings.internal_api_key = "test-internal-key"
    security_module.settings.auth_cookie_secure = False
    security_module.settings.trusted_hosts = "localhost,127.0.0.1"
    security_module.settings.cors_origins = "https://dashboard.example.com"
    security_module.settings.allow_insecure_no_auth = False

    try:
        try:
            validate_auth_configuration()
            assert False, "validate_auth_configuration should fail when production uses insecure defaults"
        except AuthConfigurationError as exc:
            assert "AUTH_COOKIE_SECURE" in str(exc)
    finally:
        security_module.settings.app_env = original_app_env
        security_module.settings.auth_password_secret = original_password_secret
        security_module.settings.auth_jwt_secret = original_jwt_secret
        security_module.settings.internal_api_key = original_internal_api_key
        security_module.settings.auth_cookie_secure = original_cookie_secure
        security_module.settings.trusted_hosts = original_trusted_hosts
        security_module.settings.cors_origins = original_cors_origins
        security_module.settings.allow_insecure_no_auth = original_allow_insecure

def test_production_auth_validation_accepts_hardened_defaults():
    """Validate that production auth validation accepts hardened defaults.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    import backend.app.core.security as security_module

    original_app_env = security_module.settings.app_env
    original_password_secret = security_module.settings.auth_password_secret
    original_jwt_secret = security_module.settings.auth_jwt_secret
    original_internal_api_key = security_module.settings.internal_api_key
    original_internal_api_keys = security_module.settings.internal_api_keys
    original_cookie_secure = security_module.settings.auth_cookie_secure
    original_trusted_hosts = security_module.settings.trusted_hosts
    original_cors_origins = security_module.settings.cors_origins
    original_allow_insecure = security_module.settings.allow_insecure_no_auth

    security_module.settings.app_env = "production"
    security_module.settings.auth_password_secret = "test-password-secret"
    security_module.settings.auth_jwt_secret = "test-jwt-secret"
    security_module.settings.internal_api_key = ""
    security_module.settings.internal_api_keys = "reader:test-internal-key:read"
    security_module.settings.auth_cookie_secure = True
    security_module.settings.trusted_hosts = "api.example.com,dashboard.example.com"
    security_module.settings.cors_origins = "https://dashboard.example.com"
    security_module.settings.allow_insecure_no_auth = False

    try:
        validate_auth_configuration()
    finally:
        security_module.settings.app_env = original_app_env
        security_module.settings.auth_password_secret = original_password_secret
        security_module.settings.auth_jwt_secret = original_jwt_secret
        security_module.settings.internal_api_key = original_internal_api_key
        security_module.settings.internal_api_keys = original_internal_api_keys
        security_module.settings.auth_cookie_secure = original_cookie_secure
        security_module.settings.trusted_hosts = original_trusted_hosts
        security_module.settings.cors_origins = original_cors_origins
        security_module.settings.allow_insecure_no_auth = original_allow_insecure

def test_refresh_token_reuse_revokes_session_chain():
    """Validate that refresh token reuse revokes session chain.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    with client_context() as (client, session_factory):
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))

        login_response = client.post("/auth/login", json={"username": "viewer", "password": "StrongPass123!"})
        assert login_response.status_code == 200
        original_refresh = login_response.cookies.get("network_monitoring_refresh")
        assert original_refresh

        restore_response = client.post("/auth/restore")
        assert restore_response.status_code == 200
        rotated_access = restore_response.json()["access_token"]
        rotated_refresh = restore_response.cookies.get("network_monitoring_refresh")
        assert rotated_refresh
        assert rotated_refresh != original_refresh

        client.cookies.set("network_monitoring_refresh", original_refresh)
        client.cookies.delete("network_monitoring_session")
        reuse_response = client.post("/auth/restore")
        assert reuse_response.status_code == 401

        client.cookies.set("network_monitoring_refresh", rotated_refresh)
        restore_after_reuse = client.post("/auth/restore")
        assert restore_after_reuse.status_code == 401

        me_after_reuse = client.get("/auth/me", headers={"authorization": f"Bearer {rotated_access}"})
        assert me_after_reuse.status_code == 401

def test_user_can_list_active_sessions_with_current_marker():
    """Validate that user can list active sessions with current marker.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    with client_context() as (client, session_factory):
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))

        login_response = client.post(
            "/auth/login",
            headers={"user-agent": "SessionTestAgent/1.0"},
            json={"username": "viewer", "password": "StrongPass123!"},
        )
        assert login_response.status_code == 200

        sessions_response = client.get("/auth/sessions", headers={"authorization": f"Bearer {login_response.json()['access_token']}"})
        assert sessions_response.status_code == 200
        payload = sessions_response.json()
        assert len(payload) == 1
        assert payload[0]["is_current"] is True
        assert payload[0]["user_agent"] == "SessionTestAgent/1.0"

def test_logout_all_revokes_other_sessions_but_keeps_current_session():
    """Validate that logout all revokes other sessions but keeps current session.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    with client_context() as (client_a, session_factory):
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))

        login_a = client_a.post(
            "/auth/login",
            headers={"user-agent": "ClientA/1.0"},
            json={"username": "viewer", "password": "StrongPass123!"},
        )
        assert login_a.status_code == 200
        token_a = login_a.json()["access_token"]

        with TestClient(app) as client_b:
            login_b = client_b.post(
                "/auth/login",
                headers={"user-agent": "ClientB/1.0"},
                json={"username": "viewer", "password": "StrongPass123!"},
            )
            assert login_b.status_code == 200
            token_b = login_b.json()["access_token"]

            sessions_before = client_a.get("/auth/sessions", headers={"authorization": f"Bearer {token_a}"})
            assert sessions_before.status_code == 200
            assert len(sessions_before.json()) == 2

            logout_all_response = client_a.post("/auth/logout-all", headers={"authorization": f"Bearer {token_a}"})
            assert logout_all_response.status_code == 200
            assert logout_all_response.json()["revoked_sessions"] == 1

            current_me = client_a.get("/auth/me", headers={"authorization": f"Bearer {token_a}"})
            revoked_me = client_b.get("/auth/me", headers={"authorization": f"Bearer {token_b}"})
            sessions_after = client_a.get("/auth/sessions", headers={"authorization": f"Bearer {token_a}"})

            assert current_me.status_code == 200
            assert revoked_me.status_code == 401
            assert sessions_after.status_code == 200
            assert len(sessions_after.json()) == 1
            assert sessions_after.json()[0]["is_current"] is True

def test_admin_can_inspect_and_revoke_user_sessions():
    """Validate that admin can inspect and revoke user sessions.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    with client_context() as (client, session_factory):
        viewer_user = run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))
        run(_create_user(session_factory, username="adminuser", password="StrongPass123!", role="admin", full_name="Admin User"))
        admin_login = client.post("/auth/login", json={"username": "adminuser", "password": "StrongPass123!"})
        assert admin_login.status_code == 200
        admin_token = admin_login.json()["access_token"]

        user_login = client.post(
            "/auth/login",
            headers={"user-agent": "ViewerClient/1.0"},
            json={"username": "viewer", "password": "StrongPass123!"},
        )
        assert user_login.status_code == 200

        sessions_response = client.get("/auth/admin/sessions?username=viewer", headers={"authorization": f"Bearer {admin_token}"})
        assert sessions_response.status_code == 200
        sessions_payload = sessions_response.json()
        assert len(sessions_payload) >= 1
        assert sessions_payload[0]["username"] == "viewer"

        revoked_response = client.post(
            f"/auth/admin/users/{viewer_user.id}/logout-all",
            headers={"authorization": f"Bearer {admin_token}"},
        )
        assert revoked_response.status_code == 200
        assert revoked_response.json()["revoked_sessions"] >= 1

def test_viewer_cannot_access_admin_mutation_routes():
    """Validate that viewer cannot access admin mutation routes.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    with client_context() as (client, session_factory):
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))

        login_response = client.post("/auth/login", json={"username": "viewer", "password": "StrongPass123!"})
        token = login_response.json()["access_token"]

        create_response = client.post(
            "/devices",
            headers={"authorization": f"Bearer {token}"},
            json={"name": "Viewer Device", "ip_address": "192.168.1.202", "device_type": "switch"},
        )
        assert create_response.status_code == 403

def test_admin_bearer_token_can_access_read_and_write_routes():
    """Validate that admin bearer token can access read and write routes.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    with client_context() as (client, session_factory):
        run(_create_user(session_factory, username="adminuser", password="StrongPass123!", role="admin", full_name="Admin User"))

        login_response = client.post("/auth/login", json={"username": "adminuser", "password": "StrongPass123!"})
        token = login_response.json()["access_token"]
        headers = {"authorization": f"Bearer {token}"}

        list_response = client.get("/devices", headers=headers)
        create_response = client.post(
            "/devices",
            headers=headers,
            json={"name": "Admin Device", "ip_address": "192.168.1.203", "device_type": "switch"},
        )

        assert list_response.status_code == 200
        assert create_response.status_code == 201

def test_admin_user_lifecycle_and_audit_logs():
    """Validate that admin user lifecycle and audit logs.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    with client_context() as (client, session_factory):
        run(_create_user(session_factory, username="adminuser", password="StrongPass123!", role="admin", full_name="Admin User"))

        admin_login = client.post("/auth/login", json={"username": "adminuser", "password": "StrongPass123!"})
        assert admin_login.status_code == 200
        headers = {"authorization": f"Bearer {admin_login.json()['access_token']}"}

        create_response = client.post(
            "/auth/admin/users",
            headers=headers,
            json={
                "username": "viewer2",
                "full_name": "Viewer Two",
                "password": "ViewerTwo@123!",
                "role": "viewer",
            },
        )
        assert create_response.status_code == 200
        created_user = create_response.json()

        update_response = client.put(
            f"/auth/admin/users/{created_user['id']}",
            headers=headers,
            json={"is_active": False, "disabled_reason": "Offboarding"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["is_active"] is False

        reset_response = client.post(
            f"/auth/admin/users/{created_user['id']}/reset-password",
            headers=headers,
            json={"new_password": "ViewerTwo@456!"},
        )
        assert reset_response.status_code == 200

        audit_response = client.get("/auth/admin/audit-logs?limit=20", headers=headers)
        users_response = client.get("/auth/admin/users", headers=headers)

        assert audit_response.status_code == 200
        actions = {item["action"] for item in audit_response.json()}
        assert "auth.admin.create_user" in actions
        assert "auth.admin.update_user" in actions
        assert "auth.admin.reset_password" in actions
        assert users_response.status_code == 200
        assert any(item["username"] == "viewer2" for item in users_response.json())

def test_user_can_change_password_and_old_password_stops_working():
    """Validate that user can change password and old password stops working.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    with client_context() as (client, session_factory):
        run(_create_user(session_factory, username="viewer", password="StrongPass123!", role="viewer"))

        login_response = client.post("/auth/login", json={"username": "viewer", "password": "StrongPass123!"})
        assert login_response.status_code == 200
        token = login_response.json()["access_token"]
        headers = {"authorization": f"Bearer {token}"}

        change_response = client.post(
            "/auth/change-password",
            headers=headers,
            json={"current_password": "StrongPass123!", "new_password": "StrongPass456!@"},
        )
        assert change_response.status_code == 200
        assert change_response.json()["username"] == "viewer"

        old_login = client.post("/auth/login", json={"username": "viewer", "password": "StrongPass123!"})
        new_login = client.post("/auth/login", json={"username": "viewer", "password": "StrongPass456!@"})

        assert old_login.status_code == 401
        assert new_login.status_code == 200

