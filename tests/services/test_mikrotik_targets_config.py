"""Multi-target parsing, compatibility, and typo rejection."""

import json

import pytest

from backend.app.core.config import settings


def _clear_compatibility_targets(monkeypatch):
    for field, value in (
        ("mikrotik_targets", ""),
        ("mikrotik_host", ""),
        ("mikrotik_port", 8728),
        ("mikrotik_username", ""),
        ("mikrotik_password", ""),
        ("ro_mikrotik_host", ""),
        ("ro_mikrotik_port", 8728),
        ("ro_mikrotik_username", ""),
        ("ro_mikrotik_password", ""),
    ):
        monkeypatch.setattr(settings, field, value)


def test_legacy_primary_and_regional_office_become_two_targets(monkeypatch):
    _clear_compatibility_targets(monkeypatch)
    monkeypatch.setattr(settings, "mikrotik_host", "192.0.2.1")
    monkeypatch.setattr(settings, "mikrotik_username", "head-user")
    monkeypatch.setattr(settings, "mikrotik_password", "head-secret")
    monkeypatch.setattr(settings, "ro_mikrotik_host", "192.0.2.2")
    monkeypatch.setattr(settings, "ro_mikrotik_port", 8729)
    monkeypatch.setattr(settings, "ro_mikrotik_username", "regional-user")
    monkeypatch.setattr(settings, "ro_mikrotik_password", "regional-secret")

    targets = settings.configured_mikrotik_targets

    assert [(target.name, target.host, target.port) for target in targets] == [
        ("primary", "192.0.2.1", 8728),
        ("regional-office", "192.0.2.2", 8729),
    ]


def test_json_targets_are_authoritative_and_support_future_sites(monkeypatch):
    _clear_compatibility_targets(monkeypatch)
    monkeypatch.setattr(settings, "mikrotik_host", "192.0.2.99")
    monkeypatch.setattr(
        settings,
        "mikrotik_targets",
        json.dumps(
            {
                "regional-office": {
                    "host": "192.0.2.2",
                    "port": 8728,
                    "username": "regional-user",
                    "password": "regional-secret",
                },
                "branch-office": {
                    "host": "192.0.2.3",
                    "port": 8729,
                    "username": "branch-user",
                    "password": "branch-secret",
                },
            }
        ),
    )

    assert [(target.name, target.host) for target in settings.configured_mikrotik_targets] == [
        ("regional-office", "192.0.2.2"),
        ("branch-office", "192.0.2.3"),
    ]


@pytest.mark.parametrize(
    "payload, message",
    [
        ("[]", "must map target names"),
        ('{"regional":{"host":"192.0.2.2","username":"u","password":"p","typo":1}}', "Unknown"),
        ('{"regional":{"host":"192.0.2.2","username":"u","password":"p","port":true}}', "port"),
        ('{"regional":{"host":"192.0.2.2","username":"","password":"p"}}', "requires"),
    ],
)
def test_invalid_json_target_configuration_fails_clearly(monkeypatch, payload, message):
    _clear_compatibility_targets(monkeypatch)
    monkeypatch.setattr(settings, "mikrotik_targets", payload)

    with pytest.raises(ValueError, match=message):
        _ = settings.configured_mikrotik_targets


def test_duplicate_compatibility_hosts_are_rejected(monkeypatch):
    _clear_compatibility_targets(monkeypatch)
    for prefix in ("mikrotik", "ro_mikrotik"):
        monkeypatch.setattr(settings, f"{prefix}_host", "192.0.2.1")
        monkeypatch.setattr(settings, f"{prefix}_username", "monitor")
        monkeypatch.setattr(settings, f"{prefix}_password", "secret")

    with pytest.raises(ValueError, match="hosts must be unique"):
        _ = settings.configured_mikrotik_targets
