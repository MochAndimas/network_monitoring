"""Provide application-wide configuration, constants, security, and time helpers for the network monitoring project."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ..core.config import internal_api_key_map, settings
from ..core.time import as_wib_aware, from_unix_timestamp, utcnow


PBKDF2_ITERATIONS = 600_000
JWT_ALGORITHM = "HS256"


class JWTValidationError(ValueError):
    """Represent j w t validation error behavior and data for application-wide configuration, constants, security, and time helpers.

    Inherits from `ValueError` to match the surrounding framework or persistence model.
    """
    pass


class AuthConfigurationError(RuntimeError):
    """Represent auth configuration error behavior and data for application-wide configuration, constants, security, and time helpers.

    Inherits from `RuntimeError` to match the surrounding framework or persistence model.
    """
    pass


@dataclass(slots=True)
class TokenPayload:
    """Represent token payload behavior and data for application-wide configuration, constants, security, and time helpers.
    """
    token_type: str
    subject: int
    jwt_id: str
    username: str
    role: str
    refresh_nonce: str | None
    issued_at: datetime
    not_before: datetime
    expires_at: datetime


def _required_secret(secret_value: str, env_name: str) -> bytes:
    """Handle the internal required secret helper logic for application-wide configuration, constants, security, and time helpers.

    Args:
        secret_value: secret value value used by this routine (type `str`).
        env_name: env name value used by this routine (type `str`).

    Returns:
        `bytes` result produced by the routine.
    """
    if not secret_value.strip():
        raise AuthConfigurationError(f"`{env_name}` must be configured for auth to work safely.")
    return secret_value.encode("utf-8")


def _password_secret() -> bytes:
    """Handle the internal password secret helper logic for application-wide configuration, constants, security, and time helpers.

    Returns:
        `bytes` result produced by the routine.
    """
    return _required_secret(settings.auth_password_secret, "AUTH_PASSWORD_SECRET")


def _jwt_secret() -> bytes:
    """Handle the internal jwt secret helper logic for application-wide configuration, constants, security, and time helpers.

    Returns:
        `bytes` result produced by the routine.
    """
    return _required_secret(settings.auth_jwt_secret, "AUTH_JWT_SECRET")


def validate_auth_configuration() -> None:
    """Validate auth configuration for application-wide configuration, constants, security, and time helpers.

    Returns:
        None. The routine is executed for its side effects.
    """
    _password_secret()
    _jwt_secret()
    _validate_production_security_defaults()


def validate_password_strength(password: str, *, username: str = "", full_name: str = "") -> None:
    """Validate password strength for application-wide configuration, constants, security, and time helpers.

    Args:
        password: password value used by this routine (type `str`).
        username: username keyword value used by this routine (type `str`, optional).
        full_name: full name keyword value used by this routine (type `str`, optional).

    Returns:
        None. The routine is executed for its side effects.
    """
    value = str(password or "")
    if len(value) < settings.auth_password_min_length:
        raise ValueError(f"Password must be at least {settings.auth_password_min_length} characters long.")
    checks = {
        "uppercase": any(ch.isupper() for ch in value),
        "lowercase": any(ch.islower() for ch in value),
        "digit": any(ch.isdigit() for ch in value),
        "symbol": any(not ch.isalnum() for ch in value),
    }
    if not all(checks.values()):
        raise ValueError("Password must include uppercase, lowercase, digit, and symbol characters.")
    lowered_password = value.lower()
    comparisons = [str(username or "").strip().lower(), str(full_name or "").strip().lower()]
    if any(item and item in lowered_password for item in comparisons):
        raise ValueError("Password must not contain the username or full name.")


def _validate_production_security_defaults() -> None:
    """Validate production security defaults for application-wide configuration, constants, security, and time helpers.

    Returns:
        None. The routine is executed for its side effects.
    """
    if not settings.is_production:
        return
    if settings.allow_insecure_no_auth:
        raise AuthConfigurationError("`ALLOW_INSECURE_NO_AUTH` must be false in production.")
    if not settings.auth_cookie_secure:
        raise AuthConfigurationError("`AUTH_COOKIE_SECURE` must be true in production.")
    if settings.normalized_auth_cookie_samesite == "none" and not settings.auth_cookie_secure:
        raise AuthConfigurationError("`AUTH_COOKIE_SAMESITE=none` requires `AUTH_COOKIE_SECURE=true`.")
    if not internal_api_key_map():
        raise AuthConfigurationError("`INTERNAL_API_KEY` or `INTERNAL_API_KEYS` must be configured in production.")
    trusted_hosts = {host.strip().lower() for host in settings.normalized_trusted_hosts}
    local_only_hosts = {"localhost", "127.0.0.1", "testserver"}
    if not trusted_hosts or trusted_hosts.issubset(local_only_hosts):
        raise AuthConfigurationError(
            "`TRUSTED_HOSTS` must include the real production hostnames; localhost-only values are not allowed in production."
        )
    cors_origins = settings.normalized_cors_origins
    if not cors_origins:
        raise AuthConfigurationError("`CORS_ORIGINS` must not be empty in production.")
    insecure_origins = [
        origin
        for origin in cors_origins
        if origin.startswith("http://") and "localhost" not in origin and "127.0.0.1" not in origin
    ]
    if insecure_origins:
        raise AuthConfigurationError("`CORS_ORIGINS` must use HTTPS in production for non-local origins.")


def _b64url_encode(value: bytes) -> str:
    """Handle the internal b64url encode helper logic for application-wide configuration, constants, security, and time helpers.

    Args:
        value: value value used by this routine (type `bytes`).

    Returns:
        `str` result produced by the routine.
    """
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    """Handle the internal b64url decode helper logic for application-wide configuration, constants, security, and time helpers.

    Args:
        value: value value used by this routine (type `str`).

    Returns:
        `bytes` result produced by the routine.
    """
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))
    except Exception as exc:
        raise JWTValidationError("Invalid JWT encoding") from exc


def _json_dumps(payload: dict[str, Any]) -> bytes:
    """Handle the internal json dumps helper logic for application-wide configuration, constants, security, and time helpers.

    Args:
        payload: payload value used by this routine (type `dict[str, Any]`).

    Returns:
        `bytes` result produced by the routine.
    """
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _timestamp(value: datetime) -> int:
    """Handle the internal timestamp helper logic for application-wide configuration, constants, security, and time helpers.

    Args:
        value: value value used by this routine (type `datetime`).

    Returns:
        `int` result produced by the routine.
    """
    return int(as_wib_aware(value).timestamp())


def _datetime_from_timestamp(value: Any, claim_name: str) -> datetime:
    """Handle the internal datetime from timestamp helper logic for application-wide configuration, constants, security, and time helpers.

    Args:
        value: value value used by this routine (type `Any`).
        claim_name: claim name value used by this routine (type `str`).

    Returns:
        `datetime` result produced by the routine.
    """
    if not isinstance(value, int):
        raise JWTValidationError(f"Invalid `{claim_name}` claim")
    return from_unix_timestamp(value)


def hash_password(password: str) -> str:
    """Handle hash password for application-wide configuration, constants, security, and time helpers.

    Args:
        password: password value used by this routine (type `str`).

    Returns:
        `str` result produced by the routine.
    """
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt + _password_secret(), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Handle verify password for application-wide configuration, constants, security, and time helpers.

    Args:
        password: password value used by this routine (type `str`).
        password_hash: password hash value used by this routine (type `str`).

    Returns:
        `bool` result produced by the routine.
    """
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


def generate_session_jwt_id() -> str:
    """Handle generate session jwt id for application-wide configuration, constants, security, and time helpers.

    Returns:
        `str` result produced by the routine.
    """
    return uuid.uuid4().hex


def hash_session_token(token: str) -> str:
    """Handle hash session token for application-wide configuration, constants, security, and time helpers.

    Args:
        token: token value used by this routine (type `str`).

    Returns:
        `str` result produced by the routine.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiry(ttl_minutes: int | None = None) -> datetime:
    """Handle session expiry for application-wide configuration, constants, security, and time helpers.

    Args:
        ttl_minutes: ttl minutes value used by this routine (type `int | None`, optional).

    Returns:
        `datetime` result produced by the routine.
    """
    minutes = ttl_minutes if ttl_minutes is not None else settings.auth_token_ttl_minutes
    return utcnow() + timedelta(minutes=minutes)


def create_access_token(
    *, subject: int, username: str, role: str, jwt_id: str, expires_at: datetime, access_nonce: str | None = None
) -> str:
    """Create access token for application-wide configuration, constants, security, and time helpers.

    Args:
        subject: subject keyword value used by this routine (type `int`).
        username: username keyword value used by this routine (type `str`).
        role: role keyword value used by this routine (type `str`).
        jwt_id: jwt id keyword value used by this routine (type `str`).
        expires_at: expires at keyword value used by this routine (type `datetime`).
        access_nonce: access nonce keyword value used by this routine (type `str | None`, optional).

    Returns:
        `str` result produced by the routine.
    """
    return _create_signed_token(
        token_type="access",
        subject=subject,
        username=username,
        role=role,
        jwt_id=jwt_id,
        expires_at=expires_at,
        access_nonce=access_nonce,
    )


def create_refresh_token(
    *, subject: int, username: str, role: str, jwt_id: str, refresh_nonce: str, expires_at: datetime
) -> str:
    """Create refresh token for application-wide configuration, constants, security, and time helpers.

    Args:
        subject: subject keyword value used by this routine (type `int`).
        username: username keyword value used by this routine (type `str`).
        role: role keyword value used by this routine (type `str`).
        jwt_id: jwt id keyword value used by this routine (type `str`).
        refresh_nonce: refresh nonce keyword value used by this routine (type `str`).
        expires_at: expires at keyword value used by this routine (type `datetime`).

    Returns:
        `str` result produced by the routine.
    """
    return _create_signed_token(
        token_type="refresh",
        subject=subject,
        username=username,
        role=role,
        jwt_id=jwt_id,
        refresh_nonce=refresh_nonce,
        expires_at=expires_at,
    )


def _create_signed_token(
    *,
    token_type: str,
    subject: int,
    username: str,
    role: str,
    jwt_id: str,
    expires_at: datetime,
    refresh_nonce: str | None = None,
    access_nonce: str | None = None,
) -> str:
    """Create signed token for application-wide configuration, constants, security, and time helpers.

    Args:
        token_type: token type keyword value used by this routine (type `str`).
        subject: subject keyword value used by this routine (type `int`).
        username: username keyword value used by this routine (type `str`).
        role: role keyword value used by this routine (type `str`).
        jwt_id: jwt id keyword value used by this routine (type `str`).
        expires_at: expires at keyword value used by this routine (type `datetime`).
        refresh_nonce: refresh nonce keyword value used by this routine (type `str | None`, optional).
        access_nonce: access nonce keyword value used by this routine (type `str | None`, optional).

    Returns:
        `str` result produced by the routine.
    """
    issued_at = utcnow()
    header = {"alg": settings.auth_jwt_algorithm or JWT_ALGORITHM, "typ": "JWT"}
    payload = {
        "token_type": token_type,
        "iss": settings.auth_jwt_issuer,
        "sub": str(subject),
        "username": username,
        "role": role,
        "jti": jwt_id,
        "iat": _timestamp(issued_at),
        "nbf": _timestamp(issued_at),
        "exp": _timestamp(expires_at),
    }
    if refresh_nonce is not None:
        payload["rti"] = refresh_nonce
    if access_nonce is not None:
        payload["ati"] = access_nonce
    encoded_header = _b64url_encode(_json_dumps(header))
    encoded_payload = _b64url_encode(_json_dumps(payload))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(_jwt_secret(), signing_input, hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{_b64url_encode(signature)}"


def decode_access_token(token: str) -> TokenPayload:
    """Handle decode access token for application-wide configuration, constants, security, and time helpers.

    Args:
        token: token value used by this routine (type `str`).

    Returns:
        `TokenPayload` result produced by the routine.
    """
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".", 2)
    except ValueError as exc:
        raise JWTValidationError("Malformed JWT") from exc

    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    expected_signature = hmac.new(_jwt_secret(), signing_input, hashlib.sha256).digest()
    provided_signature = _b64url_decode(encoded_signature)
    if not hmac.compare_digest(expected_signature, provided_signature):
        raise JWTValidationError("Invalid JWT signature")

    try:
        header = json.loads(_b64url_decode(encoded_header))
        payload = json.loads(_b64url_decode(encoded_payload))
    except json.JSONDecodeError as exc:
        raise JWTValidationError("Invalid JWT payload") from exc

    if header.get("alg") != (settings.auth_jwt_algorithm or JWT_ALGORITHM):
        raise JWTValidationError("Unsupported JWT algorithm")
    if payload.get("iss") != settings.auth_jwt_issuer:
        raise JWTValidationError("Invalid JWT issuer")

    subject_raw = payload.get("sub")
    token_type = payload.get("token_type")
    jwt_id = payload.get("jti")
    username = payload.get("username")
    role = payload.get("role")
    refresh_nonce = payload.get("rti")
    if token_type not in {"access", "refresh"}:
        raise JWTValidationError("Invalid JWT token type")
    if not isinstance(subject_raw, str) or not subject_raw.isdigit():
        raise JWTValidationError("Invalid JWT subject")
    if not isinstance(jwt_id, str) or not jwt_id:
        raise JWTValidationError("Invalid JWT ID")
    if not isinstance(username, str) or not username:
        raise JWTValidationError("Invalid JWT username")
    if not isinstance(role, str) or not role:
        raise JWTValidationError("Invalid JWT role")
    if refresh_nonce is not None and not isinstance(refresh_nonce, str):
        raise JWTValidationError("Invalid JWT refresh nonce")

    issued_at = _datetime_from_timestamp(payload.get("iat"), "iat")
    not_before = _datetime_from_timestamp(payload.get("nbf"), "nbf")
    expires_at = _datetime_from_timestamp(payload.get("exp"), "exp")
    now = utcnow()
    if not_before > now:
        raise JWTValidationError("JWT is not active yet")
    if expires_at <= now:
        raise JWTValidationError("JWT has expired")

    return TokenPayload(
        token_type=token_type,
        subject=int(subject_raw),
        jwt_id=jwt_id,
        username=username,
        role=role,
        refresh_nonce=refresh_nonce,
        issued_at=issued_at,
        not_before=not_before,
        expires_at=expires_at,
    )
