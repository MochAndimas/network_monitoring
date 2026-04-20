from __future__ import annotations

from datetime import datetime, timedelta
import os
import uuid
from zoneinfo import ZoneInfo

import httpx
import streamlit as st

from .auth_bridge import auth_bridge

API_BASE_URL = os.getenv("DASHBOARD_API_URL", "http://localhost:8000").rstrip("/")
PUBLIC_API_BASE_URL = os.getenv("DASHBOARD_PUBLIC_API_URL", "").rstrip("/")
AUTH_REFRESH_LEEWAY_SECONDS = 60
WIB = ZoneInfo("Asia/Jakarta")


def _initialize_auth_state() -> None:
    defaults = {
        "auth_token": None,
        "auth_role": None,
        "auth_username": None,
        "auth_full_name": None,
        "auth_expires_at": None,
        "dashboard_authenticated": False,
        "auth_restore_completed": False,
        "auth_login_error": None,
        "auth_bridge_request": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _hide_sidebar_navigation() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stSidebarNav"],
        [data-testid="stSidebarCollapseButton"],
        button[kind="header"],
        button[aria-label="Close sidebar"],
        button[aria-label="Collapse sidebar"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _clear_auth_state(*, restore_completed: bool = False) -> None:
    for key in (
        "auth_token",
        "auth_role",
        "auth_username",
        "auth_full_name",
        "auth_expires_at",
        "dashboard_authenticated",
        "pending_api_request",
        "auth_bridge_request",
    ):
        st.session_state.pop(key, None)
    st.session_state["auth_login_error"] = None
    st.session_state["auth_restore_completed"] = restore_completed


def _apply_auth_payload(payload: dict) -> None:
    user = payload.get("user", {})
    st.session_state["auth_token"] = payload.get("access_token")
    st.session_state["auth_role"] = user.get("role")
    st.session_state["auth_username"] = user.get("username")
    st.session_state["auth_full_name"] = user.get("full_name")
    st.session_state["auth_expires_at"] = user.get("expires_at")
    st.session_state["dashboard_authenticated"] = True
    st.session_state["auth_restore_completed"] = True
    st.session_state["auth_login_error"] = None


def _login_request(username: str, password: str, remember: bool) -> dict:
    with httpx.Client(base_url=API_BASE_URL, timeout=httpx.Timeout(10.0)) as client:
        response = client.post(
            "/auth/login",
            json={"username": username, "password": password, "remember": remember},
        )
        response.raise_for_status()
        return response.json()


def _resolve_bridge_host() -> str:
    return PUBLIC_API_BASE_URL or API_BASE_URL


def start_auth_bridge_request(action: str, payload: dict | None = None) -> str:
    request_id = str(uuid.uuid4())
    st.session_state["auth_bridge_request"] = {
        "id": request_id,
        "action": action,
        "payload": payload or {},
    }
    return request_id


def _bridge_component_key(action: str) -> str:
    normalized = str(action or "").strip().lower() or "unknown"
    return f"auth_bridge_{normalized}"


def consume_auth_bridge_response(*, component_key: str) -> dict | None:
    pending_request = st.session_state.get("auth_bridge_request")
    if not isinstance(pending_request, dict):
        return None
    response = auth_bridge(
        action=str(pending_request.get("action") or ""),
        host=_resolve_bridge_host(),
        request_id=str(pending_request.get("id") or ""),
        payload=pending_request.get("payload") or {},
        key=component_key,
    )
    if not response:
        return None
    if response.get("request_id") != pending_request.get("id"):
        return None
    st.session_state["auth_bridge_request"] = None
    return response


def _restore_not_needed() -> bool:
    if st.session_state.get("auth_restore_completed") is True and not st.session_state.get("dashboard_authenticated"):
        return True
    if not st.session_state.get("dashboard_authenticated"):
        return False
    if not st.session_state.get("auth_token"):
        return False
    if not st.session_state.get("auth_restore_completed"):
        return False
    expires_at = _parsed_auth_expiry()
    if expires_at is None:
        return False
    return expires_at > datetime.now(WIB).replace(tzinfo=None) + timedelta(seconds=AUTH_REFRESH_LEEWAY_SECONDS)


def _parsed_auth_expiry() -> datetime | None:
    raw_value = st.session_state.get("auth_expires_at")
    if not raw_value:
        return None
    try:
        expiry = datetime.fromisoformat(str(raw_value))
    except ValueError:
        return None
    if expiry.tzinfo is not None:
        return expiry.astimezone(WIB).replace(tzinfo=None)
    return expiry


def _login_error_message(bridge_response: dict) -> str:
    status = int(bridge_response.get("status", 0) or 0)
    error = str(bridge_response.get("error") or "").strip()
    request_id = str(bridge_response.get("request_id") or "").strip()
    request_suffix = f" Request ID: `{request_id}`." if request_id else ""

    if status == 0:
        return "Backend auth tidak bisa dijangkau. Cek backend/container API dan `DASHBOARD_PUBLIC_API_URL`." + request_suffix
    if status == 401:
        if error and error.lower() != "invalid username or password":
            return f"Login gagal: {error}.{request_suffix}".rstrip()
        return "Username atau password tidak valid." + request_suffix
    if status == 429:
        return f"Login ditolak sementara karena terlalu banyak percobaan. {error or 'Coba lagi beberapa menit lagi.'}{request_suffix}"
    if status == 403:
        return f"Login ditolak: {error or 'akses tidak diizinkan.'}{request_suffix}"
    if status >= 500:
        return f"Backend error saat login: {error or f'HTTP {status}'}.{request_suffix}".rstrip()
    if error:
        return f"Login gagal: {error}.{request_suffix}".rstrip()
    return f"Login gagal: HTTP {status}.{request_suffix}".rstrip()


def _login_error_message_from_exception(exc: httpx.HTTPError, *, request_id: str = "") -> str:
    response = getattr(exc, "response", None)
    if response is None:
        return "Backend auth tidak bisa dijangkau. Cek backend/container API dan `DASHBOARD_PUBLIC_API_URL`."
    error_detail = response.text
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        error_detail = str(payload.get("detail") or payload.get("message") or error_detail)
    return _login_error_message(
        {
            "request_id": request_id,
            "status": response.status_code,
            "error": error_detail,
        }
    )


def _try_direct_login(payload: dict, *, request_id: str) -> bool:
    try:
        login_payload = _login_request(
            str(payload.get("username") or "").strip(),
            str(payload.get("password") or ""),
            bool(payload.get("remember")),
        )
    except httpx.HTTPError as exc:
        st.session_state["auth_login_error"] = _login_error_message_from_exception(exc, request_id=request_id)
        st.session_state["auth_bridge_request"] = None
        return True

    _apply_auth_payload(login_payload)
    st.session_state["auth_bridge_request"] = None
    st.rerun()
    return True


def _restore_login_state() -> bool:
    if _restore_not_needed():
        return True

    pending_request = st.session_state.get("auth_bridge_request")
    if not isinstance(pending_request, dict) or pending_request.get("action") not in {"restore", "refresh"}:
        start_auth_bridge_request("restore")
        pending_request = st.session_state.get("auth_bridge_request")

    request_id = str((pending_request or {}).get("id") or "restore")
    bridge_response = consume_auth_bridge_response(component_key=_bridge_component_key("restore"))
    if bridge_response is None:
        st.caption("Restoring your session...")
        return False

    payload = bridge_response.get("payload", {})
    if bridge_response.get("ok") and payload.get("access_token"):
        _apply_auth_payload(payload)
        return True

    _clear_auth_state(restore_completed=True)
    return True


def _consume_logout_request() -> bool:
    pending_request = st.session_state.get("auth_bridge_request")
    if not isinstance(pending_request, dict) or pending_request.get("action") != "logout":
        return False

    request_id = str(pending_request.get("id") or "logout")
    bridge_response = consume_auth_bridge_response(component_key=_bridge_component_key("logout"))
    if bridge_response is None:
        st.caption("Logging out...")
        st.stop()

    _clear_auth_state(restore_completed=True)
    st.rerun()
    return True


def require_dashboard_login() -> None:
    _initialize_auth_state()
    _consume_logout_request()

    pending_request = st.session_state.get("auth_bridge_request")
    pending_action = str((pending_request or {}).get("action") or "")

    if pending_action != "login":
        if not _restore_login_state():
            st.stop()

    if st.session_state.get("dashboard_authenticated") is True and st.session_state.get("auth_token"):
        with st.sidebar:
            st.caption(f"Signed in as `{st.session_state.get('auth_username', '-')}`")
            st.caption(f"Role: `{st.session_state.get('auth_role', '-')}`")
            if st.button("Logout", use_container_width=True):
                start_auth_bridge_request(
                    "logout",
                    {"access_token": str(st.session_state.get("auth_token") or "")},
                )
                st.rerun()
        return

    _hide_sidebar_navigation()
    st.title("Dashboard Login")
    st.caption("Masukkan akun backend monitoring untuk mengakses dashboard.")

    pending_request = st.session_state.get("auth_bridge_request")
    if isinstance(pending_request, dict) and pending_request.get("action") == "login":
        request_id = str(pending_request.get("id") or "login")
        bridge_response = consume_auth_bridge_response(component_key=_bridge_component_key("login"))
        if bridge_response is None:
            if _try_direct_login(pending_request.get("payload") or {}, request_id=request_id):
                st.stop()
            st.caption("Signing in...")
            st.stop()

        payload = bridge_response.get("payload", {})
        if bridge_response.get("ok") and payload.get("access_token"):
            _apply_auth_payload(payload)
            st.rerun()

        st.session_state["auth_login_error"] = _login_error_message(bridge_response)

    login_error = st.session_state.get("auth_login_error")
    if login_error:
        st.error(str(login_error))

    with st.form("dashboard_login_form", clear_on_submit=False):
        username = st.text_input("Username", value="")
        password = st.text_input("Password", value="", type="password")
        remember = st.checkbox("Keep me signed in for 7 days")
        submitted = st.form_submit_button("Sign In", use_container_width=True)

    if submitted:
        username = username.strip()
        if not username or not password:
            st.session_state["auth_login_error"] = "Username dan password wajib diisi."
            st.warning("Username dan password wajib diisi.")
            st.stop()
        start_auth_bridge_request(
            "login",
            {"username": username, "password": password, "remember": remember},
        )
        st.rerun()

    st.stop()


def current_role() -> str | None:
    return st.session_state.get("auth_role")


def is_admin() -> bool:
    return current_role() == "admin"


def session_expiry_label() -> str:
    raw_value = st.session_state.get("auth_expires_at")
    if not raw_value:
        return "-"
    try:
        return datetime.fromisoformat(str(raw_value)).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(raw_value)
