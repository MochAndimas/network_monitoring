"""Provide shared Streamlit dashboard UI and API helpers for the network monitoring project."""

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
    """Handle the internal request headers helper logic for shared Streamlit dashboard UI and API helpers.

    Args:
        auth_token: auth token value used by this routine (type `str`).

    Returns:
        `dict[str, str]` result produced by the routine.
    """
    headers: dict[str, str] = {}
    if auth_token:
        headers["authorization"] = f"Bearer {auth_token}"
    return headers


@st.cache_resource(show_spinner=False)
def _client(api_base_url: str) -> httpx.Client:
    """Handle the internal client helper logic for shared Streamlit dashboard UI and API helpers.

    Args:
        api_base_url: api base url value used by this routine (type `str`).

    Returns:
        `httpx.Client` result produced by the routine.
    """
    return httpx.Client(
        base_url=api_base_url,
        timeout=httpx.Timeout(5.0),
    )


def _warn_backend_error(action: str, exc: httpx.HTTPError) -> None:
    """Handle the internal warn backend error helper logic for shared Streamlit dashboard UI and API helpers.

    Args:
        action: action value used by this routine (type `str`).
        exc: exc value used by this routine (type `httpx.HTTPError`).

    Returns:
        None. The routine is executed for its side effects.
    """
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
    """Handle the internal request json helper logic for shared Streamlit dashboard UI and API helpers.

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
    """Handle the internal prepare auth restore helper logic for shared Streamlit dashboard UI and API helpers.

    Returns:
        None. The routine is executed for its side effects.
    """
    st.session_state.pop("auth_token", None)
    st.session_state.pop("auth_expires_at", None)
    st.session_state.pop("auth_bridge_request", None)
    st.session_state["auth_restore_completed"] = False


def _pending_api_request(action_key: str | None = None) -> dict | None:
    """Handle the internal pending api request helper logic for shared Streamlit dashboard UI and API helpers.

    Args:
        action_key: action key value used by this routine (type `str | None`, optional).

    Returns:
        `dict | None` result produced by the routine.
    """
    payload = st.session_state.get(PENDING_API_REQUEST_KEY)
    if not isinstance(payload, dict):
        return None
    if action_key is not None and payload.get("action_key") != action_key:
        return None
    return payload


def has_pending_action(action_key: str) -> bool:
    """Handle has pending action for shared Streamlit dashboard UI and API helpers.

    Args:
        action_key: action key value used by this routine (type `str`).

    Returns:
        `bool` result produced by the routine.
    """
    return _pending_api_request(action_key) is not None


def _clear_pending_action(action_key: str | None = None) -> None:
    """Handle the internal clear pending action helper logic for shared Streamlit dashboard UI and API helpers.

    Args:
        action_key: action key value used by this routine (type `str | None`, optional).

    Returns:
        None. The routine is executed for its side effects.
    """
    payload = _pending_api_request(action_key)
    if payload is not None:
        st.session_state.pop(PENDING_API_REQUEST_KEY, None)


def _queue_pending_action(action_key: str, method: str, path: str, payload, fallback) -> None:
    """Handle the internal queue pending action helper logic for shared Streamlit dashboard UI and API helpers.

    Args:
        action_key: action key value used by this routine (type `str`).
        method: method value used by this routine (type `str`).
        path: path value used by this routine (type `str`).
        payload: payload value used by this routine.
        fallback: fallback value used by this routine.

    Returns:
        None. The routine is executed for its side effects.
    """
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
    """Handle the internal request with auth recovery helper logic for shared Streamlit dashboard UI and API helpers.

    Args:
        method: method value used by this routine (type `str`).
        path: path value used by this routine (type `str`).
        payload: payload keyword value used by this routine (optional).
        timeout: timeout keyword value used by this routine (type `float`).
        fallback: fallback keyword value used by this routine.
        api_base_url: api base url keyword value used by this routine (type `str`, optional).
        auth_token: auth token keyword value used by this routine (type `str`, optional).
        action: action keyword value used by this routine (type `str`).
        rerun_on_401: rerun on 401 keyword value used by this routine (type `bool`, optional).
        action_key: action key keyword value used by this routine (type `str | None`, optional).

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
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
    """Handle the internal cached get json helper logic for shared Streamlit dashboard UI and API helpers.

    Args:
        path: path value used by this routine (type `str`).
        timeout: timeout value used by this routine (type `float`).
        api_base_url: api base url value used by this routine (type `str`).
        auth_token: auth token value used by this routine (type `str`).

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
    return _request_json("GET", path, timeout=timeout, api_base_url=api_base_url, auth_token=auth_token)


@st.cache_data(show_spinner=False, ttl=GET_CACHE_TTL_SECONDS)
def _cached_get_json_map(
    request_items: tuple[tuple[str, str], ...],
    api_base_url: str,
    auth_token: str,
) -> dict[str, object]:
    """Handle the internal cached get json map helper logic for shared Streamlit dashboard UI and API helpers.

    Args:
        request_items: request items value used by this routine (type `tuple[tuple[str, str], ...]`).
        api_base_url: api base url value used by this routine (type `str`).
        auth_token: auth token value used by this routine (type `str`).

    Returns:
        `dict[str, object]` result produced by the routine.
    """
    payload: dict[str, object] = {}
    for name, path in request_items:
        payload[name] = _request_json("GET", path, api_base_url=api_base_url, auth_token=auth_token)
    return payload


@st.cache_data(show_spinner=False, ttl=GET_CACHE_TTL_SLOW_SECONDS)
def _cached_get_json_slow(path: str, timeout: float, api_base_url: str, auth_token: str):
    """Handle the internal cached get json slow helper logic for shared Streamlit dashboard UI and API helpers.

    Args:
        path: path value used by this routine (type `str`).
        timeout: timeout value used by this routine (type `float`).
        api_base_url: api base url value used by this routine (type `str`).
        auth_token: auth token value used by this routine (type `str`).

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
    return _request_json("GET", path, timeout=timeout, api_base_url=api_base_url, auth_token=auth_token)


@st.cache_data(show_spinner=False, ttl=GET_CACHE_TTL_SLOW_SECONDS)
def _cached_get_json_map_slow(
    request_items: tuple[tuple[str, str], ...],
    api_base_url: str,
    auth_token: str,
) -> dict[str, object]:
    """Handle the internal cached get json map slow helper logic for shared Streamlit dashboard UI and API helpers.

    Args:
        request_items: request items value used by this routine (type `tuple[tuple[str, str], ...]`).
        api_base_url: api base url value used by this routine (type `str`).
        auth_token: auth token value used by this routine (type `str`).

    Returns:
        `dict[str, object]` result produced by the routine.
    """
    payload: dict[str, object] = {}
    for name, path in request_items:
        payload[name] = _request_json("GET", path, api_base_url=api_base_url, auth_token=auth_token)
    return payload


def _is_slow_changing_path(path: str) -> bool:
    """Handle the internal is slow changing path helper logic for shared Streamlit dashboard UI and API helpers.

    Args:
        path: path value used by this routine (type `str`).

    Returns:
        `bool` result produced by the routine.
    """
    normalized = str(path or "").lower()
    return (
        normalized.startswith("/devices/options")
        or normalized.startswith("/devices/meta/types")
        or normalized.startswith("/thresholds")
    )


def _cached_get_by_profile(path: str, timeout: float, api_base_url: str, auth_token: str):
    """Handle the internal cached get by profile helper logic for shared Streamlit dashboard UI and API helpers.

    Args:
        path: path value used by this routine (type `str`).
        timeout: timeout value used by this routine (type `float`).
        api_base_url: api base url value used by this routine (type `str`).
        auth_token: auth token value used by this routine (type `str`).

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
    if _is_slow_changing_path(path):
        return _cached_get_json_slow(path, timeout, api_base_url, auth_token)
    return _cached_get_json(path, timeout, api_base_url, auth_token)


def _cached_get_map_by_profile(
    request_items: tuple[tuple[str, str], ...],
    api_base_url: str,
    auth_token: str,
) -> dict[str, object]:
    """Handle the internal cached get map by profile helper logic for shared Streamlit dashboard UI and API helpers.

    Args:
        request_items: request items value used by this routine (type `tuple[tuple[str, str], ...]`).
        api_base_url: api base url value used by this routine (type `str`).
        auth_token: auth token value used by this routine (type `str`).

    Returns:
        `dict[str, object]` result produced by the routine.
    """
    if request_items and all(_is_slow_changing_path(path) for _, path in request_items):
        return _cached_get_json_map_slow(request_items, api_base_url, auth_token)
    return _cached_get_json_map(request_items, api_base_url, auth_token)


def get_json(path: str, fallback):
    """Return json for shared Streamlit dashboard UI and API helpers.

    Args:
        path: path value used by this routine (type `str`).
        fallback: fallback value used by this routine.

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
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
    """Handle post json for shared Streamlit dashboard UI and API helpers.

    Args:
        path: path value used by this routine (type `str`).
        payload: payload value used by this routine (type `dict | None`).
        fallback: fallback value used by this routine.
        action_key: action key keyword value used by this routine (type `str | None`, optional).

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
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
    """Handle put json for shared Streamlit dashboard UI and API helpers.

    Args:
        path: path value used by this routine (type `str`).
        payload: payload value used by this routine (type `dict`).
        fallback: fallback value used by this routine.
        action_key: action key keyword value used by this routine (type `str | None`, optional).

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
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
    """Delete json for shared Streamlit dashboard UI and API helpers.

    Args:
        path: path value used by this routine (type `str`).
        fallback: fallback value used by this routine (optional).
        action_key: action key keyword value used by this routine (type `str | None`, optional).

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
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
    """Return json map for shared Streamlit dashboard UI and API helpers.

    Args:
        requests: requests value used by this routine (type `Mapping[str, tuple[str, object]]`).

    Returns:
        `dict[str, object]` result produced by the routine.
    """
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
    """Handle paged items for shared Streamlit dashboard UI and API helpers.

    Args:
        payload: payload value used by this routine.
        fallback: fallback value used by this routine (type `list[dict] | None`, optional).

    Returns:
        `list[dict]` result produced by the routine.
    """
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            return items
    return fallback or []


def paged_meta(payload) -> dict:
    """Handle paged meta for shared Streamlit dashboard UI and API helpers.

    Args:
        payload: payload value used by this routine.

    Returns:
        `dict` result produced by the routine.
    """
    if isinstance(payload, dict):
        meta = payload.get("meta")
        if isinstance(meta, dict):
            return meta
    return {"total": 0, "limit": 0, "offset": 0}
