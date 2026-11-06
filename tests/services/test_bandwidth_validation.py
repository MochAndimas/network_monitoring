"""Operator measurements remain exact, read-only and scoped to their policy."""

import argparse
import json
import stat
import sys
from dataclasses import replace
from ipaddress import IPv4Address, IPv4Network
from time import time_ns

import pytest
from sqlalchemy import func, select

from backend.app.bandwidth import collector_health, diagnostics
from backend.app.bandwidth.contracts import FlowPolicy
from backend.app.bandwidth.ingestion_config import IngestionPolicy
from backend.app.bandwidth.spool import source_manifest
from backend.app.bandwidth.validation import TransferBaseline, compare_transfer
from backend.app.models.bandwidth_ingestion import BandwidthFlow, BandwidthFlowStream
from backend.app.services.bandwidth_ingestion_service import ingest_segment
from backend.app.services.bandwidth_validation_service import capture_baseline, ingestion_status, observe_transfer
from tests.bandwidth_fixtures import record, sealed
from tests.test_utils import run


@pytest.fixture
def policy():
    return IngestionPolicy(
        FlowPolicy(1, frozenset({13}), frozenset({10}), (IPv4Network("192.168.1.0/24"),), ()),
        IPv4Address("192.0.2.1"),
    )


def test_baseline_strict_roundtrip_and_rejects_coercion(policy):
    value = TransferBaseline(1, policy.digest, "192.168.1.31", "1800000000000000001", "9007199254740993")
    assert TransferBaseline.parse(value.payload()) == value
    for changes in (
        {"version": True},
        {"version": 2},
        {"router_id": True},
        {"policy_digest": "not-a-digest"},
        {"created_ns": 1800000000000000001},
        {"created_ns": "0"},
        {"last_flow_id": "-1"},
        {"last_flow_id": str(2**63)},
        {"last_flow_id": "01"},
        {"device_ip": "::1"},
        {"extra": "ignored?"},
    ):
        with pytest.raises(ValueError):
            TransferBaseline.parse({**value.payload(), **changes})


def test_transfer_comparison_is_exact_at_tolerance_boundary_above_bigint():
    target = 2**65
    allowed = target * 500 // 10000
    expected = {"download": target}
    assert compare_transfer({"download": target + allowed}, expected, 500)["verdict"] == "within_tolerance"
    result = compare_transfer({"download": target + allowed + 1}, expected, 500)
    assert result["verdict"] == "outside_tolerance"
    assert result["completeness"] == "unverified"
    assert result["directions"]["download"]["expected_payload_bytes"] == str(target)
    assert compare_transfer({"download": 0}, {"download": 1}, 0)["verdict"] == "outside_tolerance"
    assert compare_transfer({"download": 0}, {"download": 1}, 10000)["verdict"] == "outside_tolerance"
    for observed, expected, tolerance in (
        ({"upload": True}, {"upload": 1}, 0),
        ({"upload": 1}, {}, 0),
        ({"upload": 1}, {"upload": 0}, 500),
        ({"upload": 1}, {"upload": 1}, True),
        ({"upload": 1}, {"upload": 1}, 10001),
    ):
        with pytest.raises(ValueError):
            compare_transfer(observed, expected, tolerance)


def test_status_requires_matching_live_worker_and_baseline_lan(inventory_sessions, policy):
    async def scenario():
        async with inventory_sessions() as db:
            assert not (await ingestion_status(db, policy))["worker_alive"]
            with pytest.raises(ValueError, match="matching_worker_not_alive"):
                await capture_baseline(db, policy, "192.168.1.31")
            with pytest.raises(ValueError, match="device_outside_policy"):
                await capture_baseline(db, policy, "203.0.113.1")
        for identity, digest, status, age in (
            ("stale", policy.digest, "idle", 46),
            ("wrong", "0" * 64, "idle", 0),
            ("failed", policy.digest, "error", 0),
            ("future", policy.digest, "idle", -60),
        ):
            async with inventory_sessions.begin() as db:
                db.add(
                    BandwidthFlowStream(
                        stream_id=identity,
                        router_id=1,
                        policy_digest=digest,
                        heartbeat_ns=time_ns() - age * 10**9,
                        status=status,
                    )
                )
        async with inventory_sessions() as db:
            report = await ingestion_status(db, policy)
            assert not report["worker_alive"] and len(report["streams"]) == 4

    run(scenario())


def test_observations_exclude_prior_flows_other_ips_and_other_policies(inventory_sessions, tmp_path, policy):
    source = source_manifest(tmp_path, router_id=1)

    async def ingest(payload, source=source, policy=policy):
        async with inventory_sessions.begin() as db:
            await ingest_segment(db, source, sealed(tmp_path, payload), payload, policy)

    async def scenario():
        await ingest(record(bytes=100))
        async with inventory_sessions() as db:
            baseline = await capture_baseline(db, policy, "192.168.1.31")
        await ingest(
            record(
                bytes=200,
                time_flow_start_ns=int(baseline.created_ns) - 100,
                time_flow_end_ns=int(baseline.created_ns) + 100,
            )
        )
        await ingest(record(bytes=300, src_addr="192.168.1.99"))
        await ingest(record(bytes=400, in_if=10, out_if=13, src_addr="1.1.1.1", post_nat_dst_addr="192.168.1.31"))
        # A different stream policy on the same router must not contaminate this window.
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        other_source = source_manifest(other_dir, router_id=1)
        other_policy = replace(policy, flow=replace(policy.flow, excluded_remote_networks=(IPv4Network("10.0.0.0/8"),)))
        await ingest(record(bytes=999), other_source, other_policy)
        regional_dir = tmp_path / "regional"
        regional_dir.mkdir()
        regional_source = source_manifest(regional_dir, router_id=2)
        regional_policy = replace(policy, flow=replace(policy.flow, router_id=2))
        await ingest(record(bytes=999) + b"not-json\n", regional_source, regional_policy)
        async with inventory_sessions() as db:
            observed = await observe_transfer(db, policy, baseline)
            assert observed == {"upload": 200, "download": 400, "flow_count": 2, "flows_started_before_baseline": 1}
            assert await db.scalar(select(func.count()).select_from(BandwidthFlow)) == 6
            report = await ingestion_status(db, policy)
            assert report["accepted_flows"] == "5" and report["last_flow_id"] == "5"
            assert report["rejected_records"] == {} and report["counter_scope"] == "all_router_streams"
            assert (await ingestion_status(db, regional_policy))["rejected_records"] == {"invalid_json": "1"}
            with pytest.raises(ValueError, match="baseline_policy_mismatch"):
                await observe_transfer(db, other_policy, baseline)
        # Diagnostic reads do not write records or advance a spool checkpoint.
        async with inventory_sessions() as db:
            assert (await observe_transfer(db, policy, baseline)) == observed

    run(scenario())


def test_cli_failure_redacts_database_exception_context(monkeypatch, capsys):
    class Engine:
        async def dispose(self):
            pass

    async def fail(_args):
        raise RuntimeError("mysql://operator:do-not-print-this@database/private")

    monkeypatch.setattr(diagnostics, "run", fail)
    monkeypatch.setattr(diagnostics, "engine", Engine())
    monkeypatch.setattr(sys, "argv", ["diagnostics", "status"])
    with pytest.raises(SystemExit) as error:
        diagnostics.main()
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert "do-not-print-this" not in captured.out + captured.err
    assert json.loads(captured.out)["error"] == "diagnostic_failed"


def test_collector_readiness_never_initializes_or_rebinds_spool(tmp_path):
    assert not collector_health.collector_ready(tmp_path, 1)
    assert list(tmp_path.iterdir()) == []
    source_manifest(tmp_path, router_id=1)
    manifest = tmp_path / ".stream.json"
    original = manifest.read_bytes()
    assert collector_health.collector_ready(tmp_path, 1)
    assert not collector_health.collector_ready(tmp_path, 2)
    assert not collector_health.collector_ready(tmp_path, True)
    assert manifest.read_bytes() == original
    manifest.write_text("not-json")
    assert not collector_health.collector_ready(tmp_path, 1)
    assert manifest.read_text() == "not-json"


def test_collector_health_cli_uses_explicit_router_binding(tmp_path, monkeypatch):
    monkeypatch.setenv("BANDWIDTH_SPOOL_DIRECTORY", str(tmp_path))
    monkeypatch.delenv("BANDWIDTH_ROUTER_ID", raising=False)
    with pytest.raises(SystemExit) as error:
        collector_health.main()
    assert error.value.code == 1
    source_manifest(tmp_path, router_id=2)
    for router, expected in (("not-an-id", 1), ("1", 1), ("2", 0)):
        monkeypatch.setenv("BANDWIDTH_ROUTER_ID", router)
        with pytest.raises(SystemExit) as error:
            collector_health.main()
        assert error.value.code == expected


def test_cli_baseline_is_private_exclusive_and_verify_is_read_only(inventory_sessions, tmp_path, policy, monkeypatch):
    config = tmp_path / "policy.json"
    config.write_text(
        json.dumps(
            {
                "router_id": 1,
                "exporter": "192.0.2.1",
                "lan_interfaces": [13],
                "wan_interfaces": [10],
                "lan_networks": ["192.168.1.0/24"],
                "excluded_remote_networks": [],
            }
        )
    )
    output = tmp_path / "baseline.json"
    monkeypatch.setattr(diagnostics, "SessionLocal", inventory_sessions)
    source = source_manifest(tmp_path, router_id=1)
    payload = record()

    async def scenario():
        async with inventory_sessions.begin() as db:
            await ingest_segment(db, source, sealed(tmp_path, payload), payload, policy)
        args = argparse.Namespace(policy=str(config), command="baseline", device_ip="192.168.1.31", output=str(output))
        result, code = await diagnostics.run(args)
        assert code == 0 and TransferBaseline.parse(result).last_flow_id == "1"
        assert stat.S_IMODE(output.stat().st_mode) == 0o600
        with pytest.raises(FileExistsError):
            await diagnostics.run(args)
        async with inventory_sessions.begin() as db:
            await ingest_segment(db, source, sealed(tmp_path, payload), payload, policy)
        result, code = await diagnostics.run(
            argparse.Namespace(
                policy=str(config),
                command="verify",
                baseline=str(output),
                upload_bytes=4178,
                download_bytes=None,
                tolerance_bps=0,
            )
        )
        assert code == 0 and result["observed_upload_bytes"] == "4178"
        assert result["completeness"] == "unverified"

    run(scenario())
