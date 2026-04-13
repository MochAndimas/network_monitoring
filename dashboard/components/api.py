from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping

import httpx
import streamlit as st


API_BASE_URL = os.getenv("DASHBOARD_API_URL", "http://localhost:8000").rstrip("/")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
GET_CACHE_TTL_SECONDS = 2


def _request_headers() -> dict:
    if not INTERNAL_API_KEY:
        return {}
    return {"x-api-key": INTERNAL_API_KEY}


async def _request_json_async(method: str, path: str, payload: dict | None = None, timeout: float = 5.0):
    url = f"{API_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=timeout, headers=_request_headers()) as client:
        response = await client.request(method, url, json=payload)
        response.raise_for_status()
        return response.json()


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, object] = {}
    error: dict[str, BaseException] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive for embedded runtimes
            error["value"] = exc

    import threading

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "value" in error:
        raise error["value"]
    return result.get("value")


def _warn_backend_error(action: str, exc: httpx.HTTPError) -> None:
    response = getattr(exc, "response", None)
    if response is not None:
        st.warning(f"{action}: HTTP {response.status_code} dari backend.")
        return
    st.warning(f"{action}: backend tidak bisa dijangkau.")


@st.cache_data(show_spinner=False, ttl=GET_CACHE_TTL_SECONDS)
def _cached_get_json(path: str, timeout: float, api_base_url: str, internal_api_key: str):
    del api_base_url, internal_api_key
    return _run_async(_request_json_async("GET", path, timeout=timeout))


@st.cache_data(show_spinner=False, ttl=GET_CACHE_TTL_SECONDS)
def _cached_get_json_map(request_items: tuple[tuple[str, str], ...], api_base_url: str, internal_api_key: str):
    del api_base_url, internal_api_key
    requests = {name: (path, None) for name, path in request_items}
    return _run_async(_get_json_map_async(requests))


def get_json(path: str, fallback):
    try:
        return _cached_get_json(path, 5.0, API_BASE_URL, INTERNAL_API_KEY)
    except httpx.HTTPError as exc:
        _warn_backend_error("Gagal mengambil data", exc)
        return fallback


def post_json(path: str, payload: dict | None, fallback):
    try:
        return _run_async(_request_json_async("POST", path, payload=payload, timeout=20.0))
    except httpx.HTTPError as exc:
        _warn_backend_error("Gagal mengirim request", exc)
        return fallback


def put_json(path: str, payload: dict, fallback):
    try:
        return _run_async(_request_json_async("PUT", path, payload=payload, timeout=20.0))
    except httpx.HTTPError as exc:
        _warn_backend_error("Gagal mengirim update", exc)
        return fallback


async def _get_json_map_async(requests: Mapping[str, tuple[str, object]]) -> dict[str, object]:
    async with httpx.AsyncClient(headers=_request_headers()) as client:
        async def fetch(name: str, path: str, fallback):
            url = f"{API_BASE_URL}{path}"
            try:
                response = await client.get(url, timeout=5.0)
                response.raise_for_status()
                return name, response.json()
            except httpx.HTTPError as exc:
                return name, exc, fallback

        results = await asyncio.gather(
            *(fetch(name, path, fallback) for name, (path, fallback) in requests.items())
        )

    payload: dict[str, object] = {}
    for item in results:
        if len(item) == 2:
            name, data = item
            payload[name] = data
            continue
        name, exc, fallback = item
        _warn_backend_error(f"Gagal mengambil data untuk {name}", exc)
        payload[name] = fallback
    return payload


def get_json_map(requests: Mapping[str, tuple[str, object]]) -> dict[str, object]:
    request_items = tuple((name, path) for name, (path, _fallback) in requests.items())
    payload = _cached_get_json_map(request_items, API_BASE_URL, INTERNAL_API_KEY)
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
