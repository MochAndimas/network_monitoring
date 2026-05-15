"""Define test module behavior for `tests/services/test_config_file_backed_secrets.py`.

This module contains automated regression and validation scenarios.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings

SettingsFactory = cast(Any, Settings)


def test_file_backed_secret_paths_are_rejected_outside_production(tmp_path: Path):
    secret_file = tmp_path / "auth_jwt_secret.txt"
    secret_file.write_text("jwt-secret-from-file\n", encoding="utf-8")

    with pytest.raises(ValidationError) as exc_info:
        SettingsFactory(
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

    settings = SettingsFactory(
        _env_file=None,
        app_env="production",
        auth_jwt_secret_file=str(jwt_secret_file),
        auth_password_secret_file=str(password_secret_file),
    )

    assert settings.auth_jwt_secret == "jwt-secret-from-file"
    assert settings.auth_password_secret == "password-secret-from-file"


def test_nested_settings_groups_preserve_flat_env_contract() -> None:
    settings = SettingsFactory(
        _env_file=None,
        database_url="sqlite:///local.db",
        db_pool_size=5,
        auth_jwt_secret="jwt-secret",
        auth_password_secret="password-secret",
        scheduler_timezone="UTC",
        raw_metric_retention_days=14,
        database_auto_create_tables=True,
    )

    assert settings.database.url == "sqlite:///local.db"
    assert settings.database.pool_size == 5
    assert settings.auth.jwt_secret == "jwt-secret"
    assert settings.scheduler.timezone == "UTC"
    assert settings.retention.raw_metric_days == 14
    assert settings.database.auto_create_tables is True

    settings.auth_jwt_secret = "rotated-jwt-secret"

    assert settings.auth.jwt_secret == "rotated-jwt-secret"

