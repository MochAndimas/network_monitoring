from __future__ import annotations

import os
from collections.abc import Mapping

import httpx
import streamlit as st


API_BASE_URL = os.getenv("DASHBOARD_API_URL", "http://localhost:8000").rstrip("/")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
GET_CACHE_TTL_SECONDS = 2


def _request_headers(internal_api_key: str) -> dict[str, str]:
    if not internal_api_key:
        return {}
    return {"x-api-key": internal_api_key}


@st.cache_resource(show_spinner=False)
def _client(api_base_url: str, internal_api_key: str) -> httpx.Client:
    return httpx.Client(
        base_url=api_base_url,
        headers=_request_headers(internal_api_key),
        timeout=httpx.Timeout(5.0),
    )


def _warn_backend_error(action: str, exc: httpx.HTTPError) -> None:
    response = getattr(exc, "response", None)
    if response is not None:
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
    internal_api_key: str = INTERNAL_API_KEY,
):
    client = _client(api_base_url, internal_api_key)
    response = client.request(method, path, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


@st.cache_data(show_spinner=False, ttl=GET_CACHE_TTL_SECONDS)
def _cached_get_json(path: str, timeout: float, api_base_url: str, internal_api_key: str):
    return _request_json("GET", path, timeout=timeout, api_base_url=api_base_url, internal_api_key=internal_api_key)


@st.cache_data(show_spinner=False, ttl=GET_CACHE_TTL_SECONDS)
def _cached_get_json_map(
    request_items: tuple[tuple[str, str], ...],
    api_base_url: str,
    internal_api_key: str,
) -> dict[str, object]:
    payload: dict[str, object] = {}
    for name, path in request_items:
        payload[name] = _request_json("GET", path, api_base_url=api_base_url, internal_api_key=internal_api_key)
    return payload


def get_json(path: str, fallback):
    try:
        return _cached_get_json(path, 5.0, API_BASE_URL, INTERNAL_API_KEY)
    except httpx.HTTPError as exc:
        _warn_backend_error("Gagal mengambil data", exc)
        return fallback


def post_json(path: str, payload: dict | None, fallback):
    try:
        return _request_json("POST", path, payload=payload, timeout=20.0)
    except httpx.HTTPError as exc:
        _warn_backend_error("Gagal mengirim request", exc)
        return fallback


def put_json(path: str, payload: dict, fallback):
    try:
        return _request_json("PUT", path, payload=payload, timeout=20.0)
    except httpx.HTTPError as exc:
        _warn_backend_error("Gagal mengirim update", exc)
        return fallback


def get_json_map(requests: Mapping[str, tuple[str, object]]) -> dict[str, object]:
    request_items = tuple((name, path) for name, (path, _fallback) in requests.items())
    try:
        payload = _cached_get_json_map(request_items, API_BASE_URL, INTERNAL_API_KEY)
    except httpx.HTTPError as exc:
        _warn_backend_error("Gagal mengambil data", exc)
        payload = {}
    return {
        name: payload.get(name, fallback)
        for name, (_path, fallback) in requests.items()
    }


def paged_items(payload, fallback: list[dict] | None = None) -> list[dict]:
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            return items
    return fallback or []


def paged_meta(payload) -> dict:
    if isinstance(payload, dict):
        meta = payload.get("meta")
        if isinstance(meta, dict):
            return meta
    return {"total": 0, "limit": 0, "offset": 0}
