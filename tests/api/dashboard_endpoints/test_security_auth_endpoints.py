"""Security/auth endpoint scenarios split from run-cycle regression coverage."""

from .common import _create_user, API_HEADERS, client_context, empty_checks, run


def test_internal_api_key_protects_mutation_endpoints():
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


def test_run_cycle_accepts_admin_bearer_token_after_auth_session_lookup():
    import backend.app.services.run_cycle_service as run_cycle_module

    original_internet = run_cycle_module.run_internet_checks
    original_device = run_cycle_module.run_device_checks
    original_server = run_cycle_module.run_server_checks
    original_mikrotik = run_cycle_module.run_mikrotik_checks

    try:
        run_cycle_module.run_internet_checks = empty_checks
        run_cycle_module.run_device_checks = empty_checks
        run_cycle_module.run_server_checks = empty_checks
        run_cycle_module.run_mikrotik_checks = empty_checks

        with client_context() as (client, session_factory):
            run(_create_user(session_factory, username="opsadmin", password="StrongPass123!", role="admin"))
            login_response = client.post("/auth/login", json={"username": "opsadmin", "password": "StrongPass123!"})
            assert login_response.status_code == 200

            cycle_response = client.post(
                "/system/run-cycle",
                headers={"authorization": f"Bearer {login_response.json()['access_token']}"},
            )

        assert cycle_response.status_code == 200
        assert cycle_response.json()["metrics_collected"] == 0
    finally:
        run_cycle_module.run_internet_checks = original_internet
        run_cycle_module.run_device_checks = original_device
        run_cycle_module.run_server_checks = original_server
        run_cycle_module.run_mikrotik_checks = original_mikrotik


def test_internal_api_key_protects_read_endpoints():
    with client_context() as (client, _session_factory):
        unauthorized_devices = client.get("/devices")
        authorized_devices = client.get("/devices", headers=API_HEADERS)

        assert unauthorized_devices.status_code == 401
        assert authorized_devices.status_code == 200


def test_missing_credentials_are_rejected_without_api_key_or_bearer_token():
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
