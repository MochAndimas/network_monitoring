"""Provide shared Streamlit dashboard UI and API helpers for the network monitoring project."""

from __future__ import annotations

from datetime import datetime, timedelta
import os
import uuid
from zoneinfo import ZoneInfo

import streamlit as st

from .auth_bridge import auth_bridge

API_BASE_URL = os.getenv("DASHBOARD_API_URL", "http://localhost:8000").rstrip("/")
PUBLIC_API_BASE_URL = os.getenv("DASHBOARD_PUBLIC_API_URL", "").rstrip("/")
AUTH_REFRESH_LEEWAY_SECONDS = 60
WIB = ZoneInfo("Asia/Jakarta")


def _initialize_auth_state() -> None:
    """Handle the internal initialize auth state helper logic for shared Streamlit dashboard UI and API helpers.

    Returns:
        None. The routine is executed for its side effects.
    """
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
    """Handle the internal hide sidebar navigation helper logic for shared Streamlit dashboard UI and API helpers.

    Returns:
        None. The routine is executed for its side effects.
    """
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
    """Handle the internal clear auth state helper logic for shared Streamlit dashboard UI and API helpers.

    Args:
        restore_completed: restore completed keyword value used by this routine (type `bool`, optional).

    Returns:
        None. The routine is executed for its side effects.
    """
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
    """Handle the internal apply auth payload helper logic for shared Streamlit dashboard UI and API helpers.

    Args:
        payload: payload value used by this routine (type `dict`).

    Returns:
        None. The routine is executed for its side effects.
    """
    user = payload.get("user", {})
    st.session_state["auth_token"] = payload.get("access_token")
    st.session_state["auth_role"] = user.get("role")
    st.session_state["auth_username"] = user.get("username")
    st.session_state["auth_full_name"] = user.get("full_name")
    st.session_state["auth_expires_at"] = user.get("expires_at")
    st.session_state["dashboard_authenticated"] = True
    st.session_state["auth_restore_completed"] = True
    st.session_state["auth_login_error"] = None

def _resolve_bridge_host() -> str:
    """Resolve bridge host for shared Streamlit dashboard UI and API helpers.

    Returns:
        `str` result produced by the routine.
    """
    return PUBLIC_API_BASE_URL or API_BASE_URL


def start_auth_bridge_request(action: str, payload: dict | None = None) -> str:
    """Handle start auth bridge request for shared Streamlit dashboard UI and API helpers.

    Args:
        action: action value used by this routine (type `str`).
        payload: payload value used by this routine (type `dict | None`, optional).

    Returns:
        `str` result produced by the routine.
    """
    request_id = str(uuid.uuid4())
    st.session_state["auth_bridge_request"] = {
        "id": request_id,
        "action": action,
        "payload": payload or {},
    }
    return request_id


def _bridge_component_key(action: str) -> str:
    """Handle the internal bridge component key helper logic for shared Streamlit dashboard UI and API helpers.

    Args:
        action: action value used by this routine (type `str`).

    Returns:
        `str` result produced by the routine.
    """
    normalized = str(action or "").strip().lower() or "unknown"
    return f"auth_bridge_{normalized}"


def consume_auth_bridge_response(*, component_key: str) -> dict | None:
    """Handle consume auth bridge response for shared Streamlit dashboard UI and API helpers.

    Args:
        component_key: component key keyword value used by this routine (type `str`).

    Returns:
        `dict | None` result produced by the routine.
    """
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
    """Restore not needed for shared Streamlit dashboard UI and API helpers.

    Returns:
        `bool` result produced by the routine.
    """
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
    """Handle the internal parsed auth expiry helper logic for shared Streamlit dashboard UI and API helpers.

    Returns:
        `datetime | None` result produced by the routine.
    """
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
    """Authenticate error message for shared Streamlit dashboard UI and API helpers.

    Args:
        bridge_response: bridge response value used by this routine (type `dict`).

    Returns:
        `str` result produced by the routine.
    """
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

def _restore_login_state() -> bool:
    """Restore login state for shared Streamlit dashboard UI and API helpers.

    Returns:
        `bool` result produced by the routine.
    """
    if _restore_not_needed():
        return True

    pending_request = st.session_state.get("auth_bridge_request")
    if not isinstance(pending_request, dict) or pending_request.get("action") not in {"restore", "refresh"}:
        start_auth_bridge_request("restore")
        pending_request = st.session_state.get("auth_bridge_request")

    bridge_response = consume_auth_bridge_response(component_key=_bridge_component_key("restore"))
    if bridge_response is None:
        st.caption("Memulihkan sesi...")
        return False

    payload = bridge_response.get("payload", {})
    if bridge_response.get("ok") and payload.get("access_token"):
        _apply_auth_payload(payload)
        return True

    _clear_auth_state(restore_completed=True)
    return True


def _consume_logout_request() -> bool:
    """Handle the internal consume logout request helper logic for shared Streamlit dashboard UI and API helpers.

    Returns:
        `bool` result produced by the routine.
    """
    pending_request = st.session_state.get("auth_bridge_request")
    if not isinstance(pending_request, dict) or pending_request.get("action") != "logout":
        return False

    bridge_response = consume_auth_bridge_response(component_key=_bridge_component_key("logout"))
    if bridge_response is None:
        st.caption("Memproses logout...")
        st.stop()

    _clear_auth_state(restore_completed=True)
    st.rerun()
    return True


def require_dashboard_login() -> None:
    """Handle require dashboard login for shared Streamlit dashboard UI and API helpers.

    Returns:
        None. The routine is executed for its side effects.
    """
    _initialize_auth_state()
    _consume_logout_request()

    pending_request = st.session_state.get("auth_bridge_request")
    pending_action = str((pending_request or {}).get("action") or "")

    if pending_action != "login":
        if not _restore_login_state():
            st.stop()

    if st.session_state.get("dashboard_authenticated") is True and st.session_state.get("auth_token"):
        with st.sidebar:
            st.markdown("### Sesi Pengguna")
            with st.container(border=True):
                st.caption("Akun")
                st.write(str(st.session_state.get("auth_username", "-")))
                st.caption("Peran")
                st.write(str(st.session_state.get("auth_role", "-")))
                st.caption("Kedaluwarsa")
                st.write(session_expiry_label())
            if st.button("Keluar", width="stretch"):
                start_auth_bridge_request(
                    "logout",
                    {"access_token": str(st.session_state.get("auth_token") or "")},
                )
                st.rerun()
        return

    _hide_sidebar_navigation()
    st.title("Masuk Dashboard")
    st.caption("Masuk dengan akun backend monitoring untuk membuka dashboard.")

    pending_request = st.session_state.get("auth_bridge_request")
    if isinstance(pending_request, dict) and pending_request.get("action") == "login":
        bridge_response = consume_auth_bridge_response(component_key=_bridge_component_key("login"))
        if bridge_response is None:
            st.caption("Memproses login...")
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
        remember = st.checkbox("Tetap masuk selama 7 hari")
        submitted = st.form_submit_button("Masuk", width="stretch")

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
    """Handle current role for shared Streamlit dashboard UI and API helpers.

    Returns:
        `str | None` result produced by the routine.
    """
    return st.session_state.get("auth_role")


def is_admin() -> bool:
    """Handle is admin for shared Streamlit dashboard UI and API helpers.

    Returns:
        `bool` result produced by the routine.
    """
    return current_role() == "admin"


def session_expiry_label() -> str:
    """Handle session expiry label for shared Streamlit dashboard UI and API helpers.

    Returns:
        `str` result produced by the routine.
    """
    raw_value = st.session_state.get("auth_expires_at")
    if not raw_value:
        return "-"
    try:
        return datetime.fromisoformat(str(raw_value)).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(raw_value)
