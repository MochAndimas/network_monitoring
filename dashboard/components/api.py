from __future__ import annotations

import os

import httpx
import streamlit as st


API_BASE_URL = os.getenv("DASHBOARD_API_URL", "http://localhost:8000").rstrip("/")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")


def _request_headers() -> dict:
    if not INTERNAL_API_KEY:
        return {}
    return {"x-api-key": INTERNAL_API_KEY}


def get_json(path: str, fallback):
    url = f"{API_BASE_URL}{path}"
    try:
        response = httpx.get(url, timeout=5.0, headers=_request_headers())
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        st.warning(f"Gagal mengambil data dari backend: {exc}")
        return fallback


def post_json(path: str, payload: dict | None, fallback):
    url = f"{API_BASE_URL}{path}"
    try:
        response = httpx.post(url, timeout=20.0, headers=_request_headers(), json=payload)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        st.warning(f"Gagal mengirim request ke backend: {exc}")
        return fallback


def put_json(path: str, payload: dict, fallback):
    url = f"{API_BASE_URL}{path}"
    try:
        response = httpx.put(url, timeout=20.0, headers=_request_headers(), json=payload)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        st.warning(f"Gagal mengirim update ke backend: {exc}")
        return fallback
