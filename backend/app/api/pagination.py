"""Shared cursor pagination helpers for API routes."""

import base64
import json
from typing import Any

from fastapi import HTTPException, status as http_status


def encode_page_cursor(payload: dict[str, Any]) -> str:
    """Encode a small keyset cursor payload into a URL-safe token."""
    raw_cursor = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw_cursor).decode("ascii").rstrip("=")


def decode_page_cursor(cursor: str, *, detail: str) -> dict[str, Any]:
    """Decode a URL-safe keyset cursor token from a public API request."""
    try:
        padded_cursor = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded_cursor.encode("ascii")).decode("utf-8"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=detail) from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=detail)
    return payload
