"""Regression tests for file-backed secret policy in settings."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings


def test_file_backed_secret_paths_are_rejected_outside_production(tmp_path: Path):
    secret_file = tmp_path / "auth_jwt_secret.txt"
    secret_file.write_text("jwt-secret-from-file\n", encoding="utf-8")

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            _env_file=None,
            app_env="development",
            auth_jwt_secret_file=str(secret_file),
        )

    assert "only allowed when APP_ENV=production" in str(exc_info.value)


def test_file_backed_secrets_are_loaded_in_production(tmp_path: Path):
    jwt_secret_file = tmp_path / "auth_jwt_secret.txt"
    password_secret_file = tmp_path / "auth_password_secret.txt"
    jwt_secret_file.write_text("jwt-secret-from-file\n", encoding="utf-8")
    password_secret_file.write_text("password-secret-from-file\n", encoding="utf-8")

    settings = Settings(
        _env_file=None,
        app_env="production",
        auth_jwt_secret_file=str(jwt_secret_file),
        auth_password_secret_file=str(password_secret_file),
    )

    assert settings.auth_jwt_secret == "jwt-secret-from-file"
    assert settings.auth_password_secret == "password-secret-from-file"

