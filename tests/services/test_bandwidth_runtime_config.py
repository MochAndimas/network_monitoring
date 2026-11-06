"""Runtime config has one source and health checks reject future heartbeats."""

import sys
from dataclasses import replace
from pathlib import Path
from time import time_ns

import pytest
from pydantic import ValidationError

from backend.app.bandwidth import inventory_worker, worker
from backend.app.bandwidth.health import observation_is_fresh
from backend.app.bandwidth.ingestion_config import load_policy
from backend.app.bandwidth.spool import source_manifest
from backend.app.core.config import Settings
from backend.app.models.bandwidth_ingestion import BandwidthFlowStream
from tests.test_utils import run


def test_inventory_cli_uses_typed_env_file_settings(tmp_path, monkeypatch):
    for key in ("BANDWIDTH_INVENTORY_TARGET_NAME", "BANDWIDTH_INVENTORY_API_HOST", "BANDWIDTH_INVENTORY_POLL_SECONDS"):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / "inventory.env"
    path.write_text(
        "BANDWIDTH_INVENTORY_TARGET_NAME=office\nBANDWIDTH_INVENTORY_API_HOST=192.0.2.1\nBANDWIDTH_INVENTORY_POLL_SECONDS=25\n"
    )
    settings = Settings(_env_file=path, app_env="development")
    monkeypatch.setattr(inventory_worker, "settings", settings)
    monkeypatch.setattr(inventory_worker, "configure_logging", lambda: None)
    captured = []

    async def capture(args):
        captured.append((args.target_name, args.api_host, args.poll_seconds))

    monkeypatch.setattr(inventory_worker, "run", capture)
    monkeypatch.setattr(sys, "argv", ["inventory_worker", "health"])
    inventory_worker.main()
    assert captured == [("office", "192.0.2.1", 25.0)]
    monkeypatch.setattr(sys, "argv", ["inventory_worker", "once", "--target-name", "override", "--poll-seconds", "10"])
    inventory_worker.main()
    assert captured[-1] == ("override", "192.0.2.1", 10.0)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0, -1, 3601])
def test_inventory_poll_configuration_rejects_invalid_numbers(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="development", bandwidth_inventory_poll_seconds=value)


def test_worker_health_checks_current_stream_policy_router_and_clock(inventory_sessions, tmp_path, monkeypatch):
    source = source_manifest(tmp_path, router_id=1)
    policy = load_policy(Path("goflow2/flow-policy.example.json"))
    now = time_ns()
    monkeypatch.setattr(worker, "SessionLocal", inventory_sessions)
    monkeypatch.setattr(worker, "time_ns", lambda: now)
    monkeypatch.setattr(worker.settings, "bandwidth_ingestion_enabled", True)
    monkeypatch.setattr(worker.settings, "bandwidth_flow_policy_file", "fixture.json")
    monkeypatch.setattr(worker.settings, "bandwidth_spool_directory", str(tmp_path))
    monkeypatch.setattr(worker, "load_policy", lambda _: policy)

    async def scenario():
        for offset, digest, status, healthy in (
            (0, policy.digest, "idle", True),
            (-45 * 10**9, policy.digest, "running", True),
            (-46 * 10**9, policy.digest, "idle", False),
            (1, policy.digest, "idle", False),
            (0, "0" * 64, "idle", False),
            (0, policy.digest, "error", False),
        ):
            async with inventory_sessions.begin() as db:
                await db.merge(
                    BandwidthFlowStream(
                        stream_id=source.stream_id,
                        router_id=1,
                        policy_digest=digest,
                        heartbeat_ns=now + offset,
                        status=status,
                    )
                )
            if healthy:
                await worker.run("health")
            else:
                with pytest.raises(SystemExit) as exc:
                    await worker.run("health")
                assert exc.value.code == 1
        monkeypatch.setattr(worker, "source_manifest", lambda _: replace(source, router_id=2))
        with pytest.raises(SystemExit):
            await worker.run("health")

    run(scenario())


def test_shared_freshness_boundary():
    assert observation_is_fresh(100, 100)
    assert not observation_is_fresh(101, 100)
    assert observation_is_fresh(1, 45 * 10**9 + 1)
    assert not observation_is_fresh(1, 45 * 10**9 + 2)


@pytest.mark.parametrize("field", ["bandwidth_inventory_api_port", "bandwidth_inventory_api_fallback_port"])
def test_transport_port_override_can_be_empty_but_must_be_in_range(field):
    assert getattr(Settings(_env_file=None, app_env="development", **{field: ""}), field) is None
    assert getattr(Settings(_env_file=None, app_env="development", **{field: 8331}), field) == 8331
    for value in (0, -1, 65536):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, app_env="development", **{field: value})
