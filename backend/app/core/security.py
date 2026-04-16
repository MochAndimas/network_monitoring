from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta

from ..core.config import settings
from ..core.time import utcnow


PBKDF2_ITERATIONS = 600_000


def _password_secret() -> bytes:
    seed = settings.internal_api_key or settings.bootstrap_admin_password or "network-monitoring-password-seed"
    return seed.encode("utf-8")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt + _password_secret(), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_hex, digest_hex = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt + _password_secret(), int(iterations_raw))
        return hmac.compare_digest(derived, expected)
    except Exception:
        return False


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiry() -> datetime:
    return utcnow() + timedelta(minutes=settings.auth_token_ttl_minutes)
