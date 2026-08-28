"""Regression tests for safe SNMP troubleshooting script inputs."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import pytest


def _load_snmp_script_module():
    script_path = Path(__file__).parents[1] / "scripts" / "test_snmp.py"
    spec = importlib.util.spec_from_file_location("test_snmp_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_snmp_script_requires_explicit_community():
    module = _load_snmp_script_module()
    args = argparse.Namespace(ip="192.0.2.10", community=None, label="Test printer")

    with pytest.raises(SystemExit, match="SNMP_COMMUNITY"):
        module.build_targets(args)


def test_snmp_script_builds_only_the_explicit_target():
    module = _load_snmp_script_module()
    args = argparse.Namespace(ip="192.0.2.10", community="test-community", label="Test printer")

    assert module.build_targets(args) == [("Test printer", "192.0.2.10", "test-community")]
