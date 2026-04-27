"""Define test module behavior for `tests/services/test_retention_defaults_consistency.py`.

This module contains automated regression and validation scenarios.
"""

import re
from pathlib import Path


def _find_config_retention_default(config_text: str) -> int:
    """Parse retention default from application settings model.

    Args:
        config_text: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    match = re.search(r"raw_metric_retention_days:\s*int\s*=\s*(\d+)", config_text)
    assert match is not None
    return int(match.group(1))


def _find_env_retention_default(env_text: str) -> int:
    """Parse retention default from env example file.

    Args:
        env_text: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    match = re.search(r"^RAW_METRIC_RETENTION_DAYS=(\d+)\s*$", env_text, flags=re.MULTILINE)
    assert match is not None
    return int(match.group(1))


def _find_compose_retention_defaults(compose_text: str) -> list[int]:
    """Parse retention defaults from docker compose variable fallbacks.

    Args:
        compose_text: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    matches = re.findall(r"RAW_METRIC_RETENTION_DAYS:\s*\$\{RAW_METRIC_RETENTION_DAYS:-(\d+)\}", compose_text)
    return [int(item) for item in matches]


def test_retention_default_is_consistent_across_config_env_and_compose():
    """Validate retention default consistency across core operational files.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    root = Path(__file__).resolve().parents[2]
    config_text = (root / "backend" / "app" / "core" / "config.py").read_text(encoding="utf-8")
    env_text = (root / ".env.example").read_text(encoding="utf-8")
    compose_text = (root / "docker-compose.yml").read_text(encoding="utf-8")

    config_default = _find_config_retention_default(config_text)
    env_default = _find_env_retention_default(env_text)
    compose_defaults = _find_compose_retention_defaults(compose_text)

    assert compose_defaults
    assert env_default == config_default
    assert all(item == config_default for item in compose_defaults)
