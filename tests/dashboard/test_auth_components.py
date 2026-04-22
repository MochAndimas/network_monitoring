"""Provide automated regression tests for the network monitoring project."""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx

import dashboard.components.api as api_module
import dashboard.components.auth as auth_module


class RerunTriggered(RuntimeError):
    """Represent rerun triggered behavior and data for automated regression tests.

    Inherits from `RuntimeError` to match the surrounding framework or persistence model.
    """
    pass


class StopTriggered(RuntimeError):
    """Represent stop triggered behavior and data for automated regression tests.

    Inherits from `RuntimeError` to match the surrounding framework or persistence model.
    """
    pass


class FakeStreamlit:
    """Represent fake streamlit behavior and data for automated regression tests.
    """
    def __init__(self, session_state: dict | None = None):
        """Handle the internal init helper logic for automated regression tests.

        Args:
            session_state: session state value used by this routine (type `dict | None`, optional).

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
        self.session_state = session_state or {}
        self.warnings: list[str] = []
        self.captions: list[str] = []
        self.errors: list[str] = []
        self.form_submit_value = False

    def warning(self, message: str) -> None:
        """Handle warning for automated regression tests.

        Args:
            message: message value used by this routine (type `str`).

        Returns:
            None. The routine is executed for its side effects.
        """
        self.warnings.append(message)

    def caption(self, message: str) -> None:
        """Handle caption for automated regression tests.

        Args:
            message: message value used by this routine (type `str`).

        Returns:
            None. The routine is executed for its side effects.
        """
        self.captions.append(message)

    def error(self, message: str) -> None:
        """Handle error for automated regression tests.

        Args:
            message: message value used by this routine (type `str`).

        Returns:
            None. The routine is executed for its side effects.
        """
        self.errors.append(message)

    def markdown(self, *_args, **_kwargs) -> None:
        """Handle markdown for automated regression tests.

        Args:
            *_args: Additional positional values accepted by this routine.
            **_kwargs: Additional keyword values accepted by this routine.

        Returns:
            None. The routine is executed for its side effects.
        """
        return None

    def title(self, *_args, **_kwargs) -> None:
        """Handle title for automated regression tests.

        Args:
            *_args: Additional positional values accepted by this routine.
            **_kwargs: Additional keyword values accepted by this routine.

        Returns:
            None. The routine is executed for its side effects.
        """
        return None

    def text_input(self, _label: str, value: str = "", **_kwargs) -> str:
        """Handle text input for automated regression tests.

        Args:
            _label: label value used by this routine (type `str`).
            value: value value used by this routine (type `str`, optional).
            **_kwargs: Additional keyword values accepted by this routine.

        Returns:
            `str` result produced by the routine.
        """
        return value

    def checkbox(self, _label: str, **_kwargs) -> bool:
        """Handle checkbox for automated regression tests.

        Args:
            _label: label value used by this routine (type `str`).
            **_kwargs: Additional keyword values accepted by this routine.

        Returns:
            `bool` result produced by the routine.
        """
        return False

    def form_submit_button(self, *_args, **_kwargs) -> bool:
        """Handle form submit button for automated regression tests.

        Args:
            *_args: Additional positional values accepted by this routine.
            **_kwargs: Additional keyword values accepted by this routine.

        Returns:
            `bool` result produced by the routine.
        """
        return self.form_submit_value

    def form(self, *_args, **_kwargs):
        """Handle form for automated regression tests.

        Args:
            *_args: Additional positional values accepted by this routine.
            **_kwargs: Additional keyword values accepted by this routine.

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
        return _NullContext()

    @property
    def sidebar(self):
        """Handle sidebar for automated regression tests.

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
        return _NullContext()

    def button(self, *_args, **_kwargs) -> bool:
        """Handle button for automated regression tests.

        Args:
            *_args: Additional positional values accepted by this routine.
            **_kwargs: Additional keyword values accepted by this routine.

        Returns:
            `bool` result produced by the routine.
        """
        return False

    def rerun(self) -> None:
        """Handle rerun for automated regression tests.

        Returns:
            None. The routine is executed for its side effects.
        """
        raise RerunTriggered()

    def stop(self) -> None:
        """Handle stop for automated regression tests.

        Returns:
            None. The routine is executed for its side effects.
        """
        raise StopTriggered()


class _NullContext:
    """Represent null context behavior and data for automated regression tests.
    """
    def __enter__(self):
        """Handle the internal enter helper logic for automated regression tests.

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
        return self

    def __exit__(self, exc_type, exc, tb):
        """Handle the internal exit helper logic for automated regression tests.

        Args:
            exc_type: exc type value used by this routine.
            exc: exc value used by this routine.
            tb: tb value used by this routine.

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
        return False


def _http_401() -> httpx.HTTPStatusError:
    """Handle the internal http 401 helper logic for automated regression tests.

    Returns:
        `httpx.HTTPStatusError` result produced by the routine.
    """
    request = httpx.Request("POST", "http://testserver/devices")
    response = httpx.Response(401, request=request)
    return httpx.HTTPStatusError("Unauthorized", request=request, response=response)


def test_restore_login_state_applies_bridge_payload(monkeypatch):
    """Handle test restore login state applies bridge payload for automated regression tests.

    Args:
        monkeypatch: monkeypatch value used by this routine.

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
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
    """Handle test restore login state marks failed restore completed for automated regression tests.

    Args:
        monkeypatch: monkeypatch value used by this routine.

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
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
    """Handle test restore not needed after failed restore for logged out user for automated regression tests.

    Args:
        monkeypatch: monkeypatch value used by this routine.

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
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
    """Handle test login error message surfaces unauthorized message for automated regression tests.

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
    error = auth_module._login_error_message(
        {
            "request_id": "req-123",
            "status": 401,
            "error": "Invalid username or password",
        }
    )

    assert error == "Username atau password tidak valid. Request ID: `req-123`."


def test_require_dashboard_login_does_not_overwrite_pending_login_with_restore(monkeypatch):
    """Handle test require dashboard login does not overwrite pending login with restore for automated regression tests.

    Args:
        monkeypatch: monkeypatch value used by this routine.

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
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
        assert False, "Expected rerun after successful login"
    except RerunTriggered:
        pass

    assert fake_st.session_state["dashboard_authenticated"] is True
    assert fake_st.session_state["auth_token"] == "token-123"


def test_require_dashboard_login_submits_bridge_login_request(monkeypatch):
    """Handle test require dashboard login submits bridge login request for automated regression tests.

    Args:
        monkeypatch: monkeypatch value used by this routine.

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
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
            "auth_bridge_request": None,
        }
    )
    fake_st.form_submit_value = True
    submitted_values = iter(["admin", "secret"])

    def fake_text_input(_label: str, value: str = "", **_kwargs) -> str:
        """Handle fake text input for automated regression tests.

        Args:
            _label: label value used by this routine (type `str`).
            value: value value used by this routine (type `str`, optional).
            **_kwargs: Additional keyword values accepted by this routine.

        Returns:
            `str` result produced by the routine.
        """
        return next(submitted_values)

    monkeypatch.setattr(auth_module, "st", fake_st)
    monkeypatch.setattr(fake_st, "text_input", fake_text_input)
    monkeypatch.setattr(auth_module, "_restore_login_state", lambda: True)

    try:
        auth_module.require_dashboard_login()
        assert False, "Expected rerun after queuing browser login"
    except RerunTriggered:
        pass

    assert fake_st.session_state["auth_bridge_request"]["action"] == "login"
    assert fake_st.session_state["auth_bridge_request"]["payload"] == {
        "username": "admin",
        "password": "secret",
        "remember": False,
    }


def test_require_dashboard_login_applies_bridge_login_response(monkeypatch):
    """Handle test require dashboard login applies bridge login response for automated regression tests.

    Args:
        monkeypatch: monkeypatch value used by this routine.

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
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
    monkeypatch.setattr(
        auth_module,
        "auth_bridge",
        lambda **kwargs: {
            "request_id": kwargs["request_id"],
            "ok": True,
            "status": 200,
            "payload": {
                "access_token": "token-direct",
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
        assert False, "Expected rerun after successful bridge login"
    except RerunTriggered:
        pass

    assert fake_st.session_state["dashboard_authenticated"] is True
    assert fake_st.session_state["auth_token"] == "token-direct"
    assert fake_st.session_state["auth_bridge_request"] is None


def test_require_dashboard_login_surfaces_bridge_login_error(monkeypatch):
    """Handle test require dashboard login surfaces bridge login error for automated regression tests.

    Args:
        monkeypatch: monkeypatch value used by this routine.

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
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
                "id": "login-3",
                "action": "login",
                "payload": {"username": "admin", "password": "wrong", "remember": True},
            },
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
            "payload": {"detail": "Invalid username or password"},
            "error": "Invalid username or password",
        },
    )

    try:
        auth_module.require_dashboard_login()
    except StopTriggered:
        pass

    assert fake_st.session_state["dashboard_authenticated"] is False
    assert fake_st.session_state["auth_login_error"] == "Username atau password tidak valid. Request ID: `login-3`."


def test_post_json_queues_pending_request_on_401_and_replays_after_restore(monkeypatch):
    """Handle test post json queues pending request on 401 and replays after restore for automated regression tests.

    Args:
        monkeypatch: monkeypatch value used by this routine.

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
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
        auth_token: str = "",
    ):
        """Handle fake request json for automated regression tests.

        Args:
            method: method value used by this routine (type `str`).
            path: path value used by this routine (type `str`).
            payload: payload keyword value used by this routine (type `dict | None`, optional).
            timeout: timeout keyword value used by this routine (type `float`, optional).
            api_base_url: api base url keyword value used by this routine (type `str`, optional).
            auth_token: auth token keyword value used by this routine (type `str`, optional).

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
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


def test_dashboard_api_does_not_fallback_to_service_key_without_auth_token():
    """Handle test dashboard api does not fallback to service key without auth token for automated regression tests.

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
    assert api_module._request_headers("") == {}


def test_get_json_uses_cached_get_reader(monkeypatch):
    """Handle test get json uses cached get reader for automated regression tests.

    Args:
        monkeypatch: monkeypatch value used by this routine.

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
    fake_st = FakeStreamlit(
        {
            "dashboard_authenticated": True,
            "auth_token": "token-123",
            "auth_restore_completed": True,
        }
    )
    monkeypatch.setattr(api_module, "st", fake_st)

    cached_calls: list[tuple[str, float, str, str]] = []

    def fake_cached_get_json(path: str, timeout: float, api_base_url: str, auth_token: str):
        """Handle fake cached get json for automated regression tests.

        Args:
            path: path value used by this routine (type `str`).
            timeout: timeout value used by this routine (type `float`).
            api_base_url: api base url value used by this routine (type `str`).
            auth_token: auth token value used by this routine (type `str`).

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
        cached_calls.append((path, timeout, api_base_url, auth_token))
        return {"ok": True}

    def fail_request_json(*_args, **_kwargs):
        """Handle fail request json for automated regression tests.

        Args:
            *_args: Additional positional values accepted by this routine.
            **_kwargs: Additional keyword values accepted by this routine.

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
        raise AssertionError("_request_json should not be called for get_json GET path")

    monkeypatch.setattr(api_module, "_cached_get_json", fake_cached_get_json)
    monkeypatch.setattr(api_module, "_request_json", fail_request_json)

    payload = api_module.get_json("/alerts/active", [])

    assert payload == {"ok": True}
    assert cached_calls == [("/alerts/active", 5.0, api_module.API_BASE_URL, "token-123")]


def test_get_json_keeps_401_recovery_with_cached_get_reader(monkeypatch):
    """Handle test get json keeps 401 recovery with cached get reader for automated regression tests.

    Args:
        monkeypatch: monkeypatch value used by this routine.

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
    fake_st = FakeStreamlit(
        {
            "dashboard_authenticated": True,
            "auth_token": "expired-token",
            "auth_expires_at": (datetime.now() + timedelta(minutes=5)).isoformat(),
            "auth_restore_completed": True,
        }
    )
    monkeypatch.setattr(api_module, "st", fake_st)

    def fake_cached_get_json(path: str, timeout: float, api_base_url: str, auth_token: str):
        """Handle fake cached get json for automated regression tests.

        Args:
            path: path value used by this routine (type `str`).
            timeout: timeout value used by this routine (type `float`).
            api_base_url: api base url value used by this routine (type `str`).
            auth_token: auth token value used by this routine (type `str`).

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
        _ = (path, timeout, api_base_url)
        if auth_token == "expired-token":
            raise _http_401()
        return {"ok": True}

    monkeypatch.setattr(api_module, "_cached_get_json", fake_cached_get_json)

    try:
        api_module.get_json("/devices/paged?limit=10&offset=0", {"items": [], "meta": {}})
        assert False, "Expected rerun when cached GET receives 401"
    except RerunTriggered:
        pass

    assert "auth_token" not in fake_st.session_state
    assert fake_st.session_state["auth_restore_completed"] is False


def test_auth_bridge_frontend_restricts_parent_origin():
    """Handle test auth bridge frontend restricts parent origin for automated regression tests.

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
    html = (auth_module.__file__)
    from pathlib import Path

    bridge_html = Path(html).resolve().parent / "auth_bridge_frontend" / "index.html"
    content = bridge_html.read_text(encoding="utf-8")

    assert 'if (args.action === "login") {' in content
    assert 'postMessage({ isStreamlitMessage: true, type, ...data }, "*")' not in content
    assert "event.origin !== trustedParentOrigin" in content
