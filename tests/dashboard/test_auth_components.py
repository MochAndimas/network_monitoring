from __future__ import annotations

from datetime import datetime, timedelta

import httpx

import dashboard.components.api as api_module
import dashboard.components.auth as auth_module


class RerunTriggered(RuntimeError):
    pass


class StopTriggered(RuntimeError):
    pass


class FakeStreamlit:
    def __init__(self, session_state: dict | None = None):
        self.session_state = session_state or {}
        self.warnings: list[str] = []
        self.captions: list[str] = []
        self.errors: list[str] = []
        self.form_submit_value = False

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def caption(self, message: str) -> None:
        self.captions.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def markdown(self, *_args, **_kwargs) -> None:
        return None

    def title(self, *_args, **_kwargs) -> None:
        return None

    def text_input(self, _label: str, value: str = "", **_kwargs) -> str:
        return value

    def checkbox(self, _label: str, **_kwargs) -> bool:
        return False

    def form_submit_button(self, *_args, **_kwargs) -> bool:
        return self.form_submit_value

    def form(self, *_args, **_kwargs):
        return _NullContext()

    @property
    def sidebar(self):
        return _NullContext()

    def button(self, *_args, **_kwargs) -> bool:
        return False

    def rerun(self) -> None:
        raise RerunTriggered()

    def stop(self) -> None:
        raise StopTriggered()


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _http_401() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://testserver/devices")
    response = httpx.Response(401, request=request)
    return httpx.HTTPStatusError("Unauthorized", request=request, response=response)


def test_restore_login_state_applies_bridge_payload(monkeypatch):
    fake_st = FakeStreamlit(
        {
            "dashboard_authenticated": False,
            "auth_token": None,
            "auth_expires_at": None,
            "auth_restore_completed": False,
            "auth_bridge_request": {"id": "restore-1", "action": "restore", "payload": {}},
        }
    )
    monkeypatch.setattr(auth_module, "st", fake_st)
    monkeypatch.setattr(
        auth_module,
        "auth_bridge",
        lambda **kwargs: {
            "request_id": kwargs["request_id"],
            "ok": True,
            "status": 200,
            "payload": {
                "access_token": "token-123",
                "user": {
                    "id": 1,
                    "username": "admin",
                    "full_name": "Admin",
                    "role": "admin",
                    "expires_at": (datetime.now() + timedelta(minutes=30)).isoformat(),
                },
            },
        },
    )

    restored = auth_module._restore_login_state()

    assert restored is True
    assert fake_st.session_state["auth_restore_completed"] is True
    assert fake_st.session_state["dashboard_authenticated"] is True
    assert fake_st.session_state["auth_token"] == "token-123"


def test_restore_login_state_marks_failed_restore_completed(monkeypatch):
    fake_st = FakeStreamlit(
        {
            "dashboard_authenticated": False,
            "auth_token": None,
            "auth_expires_at": None,
            "auth_restore_completed": False,
            "auth_bridge_request": {"id": "restore-1", "action": "restore", "payload": {}},
        }
    )
    monkeypatch.setattr(auth_module, "st", fake_st)
    monkeypatch.setattr(
        auth_module,
        "auth_bridge",
        lambda **kwargs: {
            "request_id": kwargs["request_id"],
            "ok": False,
            "status": 401,
            "payload": {"detail": "Authentication required"},
            "error": "Authentication required",
        },
    )

    restored = auth_module._restore_login_state()

    assert restored is True
    assert fake_st.session_state["auth_restore_completed"] is True
    assert fake_st.session_state.get("dashboard_authenticated") is None
    assert fake_st.session_state["auth_login_error"] is None


def test_restore_not_needed_after_failed_restore_for_logged_out_user(monkeypatch):
    fake_st = FakeStreamlit(
        {
            "dashboard_authenticated": False,
            "auth_token": None,
            "auth_expires_at": None,
            "auth_restore_completed": True,
        }
    )
    monkeypatch.setattr(auth_module, "st", fake_st)

    assert auth_module._restore_not_needed() is True


def test_login_error_message_surfaces_unauthorized_message():
    error = auth_module._login_error_message(
        {
            "request_id": "req-123",
            "status": 401,
            "error": "Invalid username or password",
        }
    )

    assert error == "Username atau password tidak valid. Request ID: `req-123`."


def test_require_dashboard_login_does_not_overwrite_pending_login_with_restore(monkeypatch):
    fake_st = FakeStreamlit(
        {
            "auth_token": None,
            "auth_role": None,
            "auth_username": None,
            "auth_full_name": None,
            "auth_expires_at": None,
            "dashboard_authenticated": False,
            "auth_restore_completed": True,
            "auth_login_error": None,
            "auth_bridge_request": {
                "id": "login-1",
                "action": "login",
                "payload": {"username": "admin", "password": "secret", "remember": True},
            },
        }
    )
    monkeypatch.setattr(auth_module, "st", fake_st)
    monkeypatch.setattr(
        auth_module,
        "auth_bridge",
        lambda **kwargs: {
            "request_id": kwargs["request_id"],
            "ok": True,
            "status": 200,
            "payload": {
                "access_token": "token-123",
                "user": {
                    "id": 1,
                    "username": "admin",
                    "full_name": "Admin",
                    "role": "admin",
                    "expires_at": (datetime.now() + timedelta(minutes=30)).isoformat(),
                },
            },
        },
    )

    try:
        auth_module.require_dashboard_login()
    except RerunTriggered:
        pass

    assert fake_st.session_state["dashboard_authenticated"] is True
    assert fake_st.session_state["auth_token"] == "token-123"


def test_require_dashboard_login_falls_back_to_direct_login_when_bridge_returns_none(monkeypatch):
    fake_st = FakeStreamlit(
        {
            "auth_token": None,
            "auth_role": None,
            "auth_username": None,
            "auth_full_name": None,
            "auth_expires_at": None,
            "dashboard_authenticated": False,
            "auth_restore_completed": True,
            "auth_login_error": None,
            "auth_bridge_request": {
                "id": "login-2",
                "action": "login",
                "payload": {"username": "admin", "password": "secret", "remember": True},
            },
        }
    )
    monkeypatch.setattr(auth_module, "st", fake_st)
    monkeypatch.setattr(auth_module, "auth_bridge", lambda **_kwargs: None)
    monkeypatch.setattr(
        auth_module,
        "_login_request",
        lambda username, password, remember: {
            "access_token": "token-direct",
            "user": {
                "id": 1,
                "username": username,
                "full_name": "Admin",
                "role": "admin",
                "expires_at": (datetime.now() + timedelta(minutes=30)).isoformat(),
            },
        },
    )

    try:
        auth_module.require_dashboard_login()
    except RerunTriggered:
        pass

    assert fake_st.session_state["dashboard_authenticated"] is True
    assert fake_st.session_state["auth_token"] == "token-direct"
    assert fake_st.session_state["auth_bridge_request"] is None


def test_post_json_queues_pending_request_on_401_and_replays_after_restore(monkeypatch):
    fake_st = FakeStreamlit(
        {
            "dashboard_authenticated": True,
            "auth_token": "expired-token",
            "auth_expires_at": (datetime.now() + timedelta(minutes=5)).isoformat(),
            "auth_restore_completed": True,
        }
    )
    monkeypatch.setattr(api_module, "st", fake_st)

    calls: list[tuple[str, object]] = []

    def fake_request_json(
        method: str,
        path: str,
        *,
        payload: dict | None = None,
        timeout: float = 5.0,
        api_base_url: str = api_module.API_BASE_URL,
        internal_api_key: str = api_module.INTERNAL_API_KEY,
        auth_token: str = "",
    ):
        calls.append((auth_token, payload))
        if auth_token == "expired-token":
            raise _http_401()
        return {"ok": True, "path": path, "payload": payload}

    monkeypatch.setattr(api_module, "_request_json", fake_request_json)

    try:
        api_module.post_json("/devices", {"name": "Router"}, None, action_key="create_device")
        assert False, "Expected rerun when access token is expired"
    except RerunTriggered:
        pass

    pending = fake_st.session_state[api_module.PENDING_API_REQUEST_KEY]
    assert pending["action_key"] == "create_device"
    assert pending["path"] == "/devices"
    assert pending["payload"] == {"name": "Router"}
    assert "auth_token" not in fake_st.session_state
    assert fake_st.session_state["auth_restore_completed"] is False

    fake_st.session_state["dashboard_authenticated"] = True
    fake_st.session_state["auth_token"] = "restored-token"
    fake_st.session_state["auth_expires_at"] = (datetime.now() + timedelta(minutes=30)).isoformat()
    fake_st.session_state["auth_restore_completed"] = True

    payload = api_module.post_json("/devices", None, None, action_key="create_device")

    assert payload == {"ok": True, "path": "/devices", "payload": {"name": "Router"}}
    assert api_module.PENDING_API_REQUEST_KEY not in fake_st.session_state
    assert calls == [
        ("expired-token", {"name": "Router"}),
        ("restored-token", {"name": "Router"}),
    ]
