"""Transport aliases remain explicit, immutable, and bound to a new stream digest."""

import hashlib
import json
from dataclasses import replace
from ipaddress import IPv4Address
from pathlib import Path

import pytest

from backend.app.bandwidth.ingestion_config import load_policy
from backend.app.bandwidth.spool import source_manifest
from backend.app.models.bandwidth_ingestion import BandwidthFlowRejection
from backend.app.services.bandwidth_ingestion_service import ingest_segment
from tests.bandwidth_fixtures import record, sealed
from tests.test_utils import run


@pytest.mark.parametrize("aliases", [None, "192.0.2.2", [1], ["::1"], ["192.0.2.2"] * 2, ["192.168.1.1"]])
def test_policy_rejects_invalid_aliases(tmp_path, aliases):
    data = json.loads(Path("goflow2/flow-policy.example.json").read_text())
    data["exporter_aliases"] = aliases
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_policy(path)


def test_legacy_digest_is_preserved_and_aliases_are_canonical(tmp_path):
    data = json.loads(Path("goflow2/flow-policy.example.json").read_text())
    policy = load_policy(Path("goflow2/flow-policy.example.json"))
    assert policy.digest == hashlib.sha256(json.dumps({"version": 1, **data}, sort_keys=True).encode()).hexdigest()
    data["exporter_aliases"] = ["192.0.2.3", "192.0.2.2"]
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(data))
    aliases = load_policy(path)
    assert aliases.digest != policy.digest
    assert (
        aliases.digest == replace(aliases, exporter_aliases=frozenset(reversed(tuple(aliases.exporter_aliases)))).digest
    )
    assert aliases.accepts_exporter("192.0.2.2")
    assert not aliases.accepts_exporter(None)
    assert not aliases.accepts_exporter(["192.0.2.2"])


def test_alias_ingestion_still_rejects_other_sources_and_policy_rebinding(inventory_sessions, tmp_path):
    original = load_policy(Path("goflow2/flow-policy.example.json"))
    policy = replace(original, exporter_aliases=frozenset({IPv4Address("192.0.2.2")}))
    source = source_manifest(tmp_path, router_id=1)
    payload = (
        record(sampler_address=str(original.exporter))
        + record(sampler_address="192.0.2.2")
        + record(sampler_address="192.0.2.99")
    )
    segment = sealed(tmp_path, payload)

    async def exercise():
        async with inventory_sessions.begin() as db:
            result = await ingest_segment(db, source, segment, payload, policy)
            assert (result.accepted, result.rejected) == (2, 1)
        async with inventory_sessions() as db:
            rejected = await db.get(BandwidthFlowRejection, (source.stream_id, "unexpected_exporter"))
            assert rejected.record_count == 1
        with pytest.raises(ValueError, match="ingestion_policy_changed"):
            async with inventory_sessions.begin() as db:
                await ingest_segment(db, source, segment, payload, original)

    run(exercise())
