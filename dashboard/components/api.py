"""HTTP client, caching, and auth recovery helpers for Streamlit pages."""

from __future__ import annotations

import os
from collections.abc import Mapping

import httpx
import streamlit as st


API_BASE_URL = os.getenv("DASHBOARD_API_URL", "http://localhost:8000").rstrip("/")
GET_CACHE_TTL_SECONDS = 5
GET_CACHE_TTL_SLOW_SECONDS = 15
PENDING_API_REQUEST_KEY = "pending_api_request"


def _request_headers(auth_token: str) -> dict[str, str]:
    """Build authorization headers for a dashboard API request."""
    headers: dict[str, str] = {}
    if auth_token:
        headers["authorization"] = f"Bearer {auth_token}"
    return headers


@st.cache_resource(show_spinner=False)
def _client(api_base_url: str) -> httpx.Client:
    """Return the cached synchronous HTTP client for one backend base URL."""
    return httpx.Client(
        base_url=api_base_url,
        timeout=httpx.Timeout(5.0),
    )


def _warn_backend_error(action: str, exc: httpx.HTTPError) -> None:
    """Show a backend error message in the dashboard UI."""
    response = getattr(exc, "response", None)
    if response is not None:
        if response.status_code == 401:
            st.warning(f"{action}: sesi login berakhir atau tidak valid.")
            return
        if response.status_code == 403:
            st.warning(f"{action}: Anda tidak punya izin untuk aksi ini.")
            return
        st.warning(f"{action}: HTTP {response.status_code} dari backend.")
        return
    st.warning(f"{action}: backend tidak bisa dijangkau.")


def _request_json(
    method: str,
    path: str,
    *,
    payload: dict | None = None,
    timeout: float = 5.0,
    api_base_url: str = API_BASE_URL,
    auth_token: str = "",
):
    """Send one JSON API request and return the decoded response payload."""
    client = _client(api_base_url)
    response = client.request(
        method,
        path,
        json=payload,
        timeout=timeout,
        headers=_request_headers(auth_token),
    )
    response.raise_for_status()
    if response.status_code == 204 or not response.content:
        return True
    return response.json()


def _prepare_auth_restore() -> None:
    """Clear local token state so the auth bridge can restore the session."""
    st.session_state.pop("auth_token", None)
    st.session_state.pop("auth_expires_at", None)
    st.session_state.pop("auth_bridge_request", None)
    st.session_state["auth_restore_completed"] = False


def _pending_api_request(action_key: str | None = None) -> dict | None:
    """Return the queued write request waiting for auth recovery."""
    payload = st.session_state.get(PENDING_API_REQUEST_KEY)
    if not isinstance(payload, dict):
        return None
    if action_key is not None and payload.get("action_key") != action_key:
        return None
    return payload


def has_pending_action(action_key: str) -> bool:
    """Return whether a write action is already queued for replay."""
    return _pending_api_request(action_key) is not None


def _clear_pending_action(action_key: str | None = None) -> None:
    """Clear a queued API write action after it succeeds or fails."""
    payload = _pending_api_request(action_key)
    if payload is not None:
        st.session_state.pop(PENDING_API_REQUEST_KEY, None)


def _queue_pending_action(action_key: str, method: str, path: str, payload, fallback) -> None:
    """Store a write request and rerun the page to restore authentication."""
    st.session_state[PENDING_API_REQUEST_KEY] = {
        "action_key": action_key,
        "method": method,
        "path": path,
        "payload": payload,
        "fallback": fallback,
    }
    _prepare_auth_restore()
    st.rerun()


def _request_with_auth_recovery(
    method: str,
    path: str,
    *,
    payload=None,
    timeout: float,
    fallback,
    api_base_url: str = API_BASE_URL,
    auth_token: str = "",
    action: str,
    rerun_on_401: bool = False,
    action_key: str | None = None,
):
    """Run an API request and retry queued writes after token restoration."""
    pending_request = _pending_api_request(action_key) if action_key else None
    request_path = str(pending_request.get("path")) if pending_request else path
    request_payload = pending_request.get("payload") if pending_request else payload
    request_fallback = pending_request.get("fallback") if pending_request else fallback
    try:
        if method == "GET" and request_payload is None:
            result = _cached_get_by_profile(request_path, timeout, api_base_url, auth_token)
        else:
            result = _request_json(
                method,
                request_path,
                payload=request_payload,
                timeout=timeout,
                api_base_url=api_base_url,
                auth_token=auth_token,
            )
        if action_key:
            _clear_pending_action(action_key)
        return result
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401 and st.session_state.get("dashboard_authenticated"):
            if action_key:
                _queue_pending_action(action_key, method, request_path, request_payload, request_fallback)
            if rerun_on_401:
                _prepare_auth_restore()
                st.rerun()
        if action_key:
            _clear_pending_action(action_key)
        _warn_backend_error(action, exc)
        return request_fallback
    except httpx.HTTPError as exc:
        if action_key:
            _clear_pending_action(action_key)
        _warn_backend_error(action, exc)
        return request_fallback


@st.cache_data(show_spinner=False, ttl=GET_CACHE_TTL_SECONDS)
def _cached_get_json(path: str, timeout: float, api_base_url: str, auth_token: str):
    """Return a short-lived cached GET response."""
    return _request_json("GET", path, timeout=timeout, api_base_url=api_base_url, auth_token=auth_token)


@st.cache_data(show_spinner=False, ttl=GET_CACHE_TTL_SECONDS)
def _cached_get_json_map(
    request_items: tuple[tuple[str, str], ...],
    api_base_url: str,
    auth_token: str,
) -> dict[str, object]:
    """Return several cached GET responses keyed by caller-defined names."""
    payload: dict[str, object] = {}
    for name, path in request_items:
        payload[name] = _request_json("GET", path, api_base_url=api_base_url, auth_token=auth_token)
    return payload


@st.cache_data(show_spinner=False, ttl=GET_CACHE_TTL_SLOW_SECONDS)
def _cached_get_json_slow(path: str, timeout: float, api_base_url: str, auth_token: str):
    """Return a longer-lived cached GET response for slow-changing data."""
    return _request_json("GET", path, timeout=timeout, api_base_url=api_base_url, auth_token=auth_token)


@st.cache_data(show_spinner=False, ttl=GET_CACHE_TTL_SLOW_SECONDS)
def _cached_get_json_map_slow(
    request_items: tuple[tuple[str, str], ...],
    api_base_url: str,
    auth_token: str,
) -> dict[str, object]:
    """Return several longer-lived cached GET responses."""
    payload: dict[str, object] = {}
    for name, path in request_items:
        payload[name] = _request_json("GET", path, api_base_url=api_base_url, auth_token=auth_token)
    return payload


def _is_slow_changing_path(path: str) -> bool:
    """Return whether a path can use the longer dashboard cache TTL."""
    normalized = str(path or "").lower()
    return (
        normalized.startswith("/devices/options")
        or normalized.startswith("/devices/meta/types")
        or normalized.startswith("/thresholds")
    )


def _cached_get_by_profile(path: str, timeout: float, api_base_url: str, auth_token: str):
    """Choose the appropriate cached GET helper for one path."""
    if _is_slow_changing_path(path):
        return _cached_get_json_slow(path, timeout, api_base_url, auth_token)
    return _cached_get_json(path, timeout, api_base_url, auth_token)


def _cached_get_map_by_profile(
    request_items: tuple[tuple[str, str], ...],
    api_base_url: str,
    auth_token: str,
) -> dict[str, object]:
    """Choose the appropriate cached GET-map helper for several paths."""
    if request_items and all(_is_slow_changing_path(path) for _, path in request_items):
        return _cached_get_json_map_slow(request_items, api_base_url, auth_token)
    return _cached_get_json_map(request_items, api_base_url, auth_token)


def get_json(path: str, fallback):
    """Fetch a dashboard API payload with auth recovery enabled."""
    return _request_with_auth_recovery(
        "GET",
        path,
        timeout=5.0,
        fallback=fallback,
        api_base_url=API_BASE_URL,
        auth_token=str(st.session_state.get("auth_token") or ""),
        action="Gagal mengambil data",
        rerun_on_401=True,
    )


def post_json(path: str, payload: dict | None, fallback, *, action_key: str | None = None):
    """POST a dashboard API payload with optional replay after auth recovery."""
    return _request_with_auth_recovery(
        "POST",
        path,
        payload=payload,
        timeout=20.0,
        fallback=fallback,
        auth_token=str(st.session_state.get("auth_token") or ""),
        action="Gagal mengirim request",
        action_key=action_key,
    )


def put_json(path: str, payload: dict, fallback, *, action_key: str | None = None):
    """PUT a dashboard API payload with optional replay after auth recovery."""
    return _request_with_auth_recovery(
        "PUT",
        path,
        payload=payload,
        timeout=20.0,
        fallback=fallback,
        auth_token=str(st.session_state.get("auth_token") or ""),
        action="Gagal mengirim update",
        action_key=action_key,
    )


def delete_json(path: str, fallback=False, *, action_key: str | None = None):
    """DELETE a dashboard API resource with optional replay after auth recovery."""
    return _request_with_auth_recovery(
        "DELETE",
        path,
        timeout=20.0,
        fallback=fallback,
        auth_token=str(st.session_state.get("auth_token") or ""),
        action="Gagal menghapus data",
        action_key=action_key,
    )


def get_json_map(requests: Mapping[str, tuple[str, object]]) -> dict[str, object]:
    """Fetch several dashboard API payloads and apply per-item fallbacks."""
    request_items = tuple((name, path) for name, (path, _fallback) in requests.items())
    try:
        payload = _cached_get_map_by_profile(request_items, API_BASE_URL, str(st.session_state.get("auth_token") or ""))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401 and st.session_state.get("dashboard_authenticated"):
            _prepare_auth_restore()
            st.rerun()
        _warn_backend_error("Gagal mengambil data", exc)
        payload = {}
    except httpx.HTTPError as exc:
        _warn_backend_error("Gagal mengambil data", exc)
        payload = {}
    return {
        name: payload.get(name, fallback)
        for name, (_path, fallback) in requests.items()
    }


def paged_items(payload, fallback: list[dict] | None = None) -> list[dict]:
    """Extract the item list from a paged API response."""
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            return items
    return fallback or []


def paged_meta(payload) -> dict:
    """Extract pagination metadata from a paged API response."""
    if isinstance(payload, dict):
        meta = payload.get("meta")
        if isinstance(meta, dict):
            return meta
    return {"total": 0, "limit": 0, "offset": 0}
