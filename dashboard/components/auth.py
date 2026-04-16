from __future__ import annotations

from datetime import datetime
import os

import httpx
import streamlit as st


API_BASE_URL = os.getenv("DASHBOARD_API_URL", "http://localhost:8000").rstrip("/")


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


def _clear_auth_state() -> None:
    for key in ("auth_token", "auth_role", "auth_username", "auth_full_name", "auth_expires_at", "dashboard_authenticated"):
        st.session_state.pop(key, None)


def _login_request(username: str, password: str) -> dict:
    with httpx.Client(base_url=API_BASE_URL, timeout=httpx.Timeout(10.0)) as client:
        response = client.post("/auth/login", json={"username": username, "password": password})
        response.raise_for_status()
        return response.json()


def _logout_request(token: str) -> None:
    with httpx.Client(base_url=API_BASE_URL, timeout=httpx.Timeout(10.0)) as client:
        client.post("/auth/logout", headers={"authorization": f"Bearer {token}"})


def require_dashboard_login() -> None:
    if st.session_state.get("dashboard_authenticated") is True and st.session_state.get("auth_token"):
        with st.sidebar:
            st.caption(f"Signed in as `{st.session_state.get('auth_username', '-')}`")
            st.caption(f"Role: `{st.session_state.get('auth_role', '-')}`")
            if st.button("Logout", use_container_width=True):
                token = str(st.session_state.get("auth_token") or "")
                if token:
                    try:
                        _logout_request(token)
                    except httpx.HTTPError:
                        pass
                _clear_auth_state()
                st.rerun()
        return

    _hide_sidebar_navigation()
    st.title("Dashboard Login")
    st.caption("Masukkan akun backend monitoring untuk mengakses dashboard.")
    with st.form("dashboard_login_form", clear_on_submit=False):
        username = st.text_input("Username", value="")
        password = st.text_input("Password", value="", type="password")
        submitted = st.form_submit_button("Sign In", use_container_width=True)

    if submitted:
        try:
            payload = _login_request(username.strip(), password)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else 0
            if status_code == 401:
                st.error("Username atau password tidak valid.")
            else:
                st.error(f"Login gagal: HTTP {status_code}.")
        except httpx.HTTPError:
            st.error("Backend auth tidak bisa dijangkau.")
        else:
            user = payload.get("user", {})
            st.session_state["auth_token"] = payload.get("access_token")
            st.session_state["auth_role"] = user.get("role")
            st.session_state["auth_username"] = user.get("username")
            st.session_state["auth_full_name"] = user.get("full_name")
            st.session_state["auth_expires_at"] = user.get("expires_at")
            st.session_state["dashboard_authenticated"] = True
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
