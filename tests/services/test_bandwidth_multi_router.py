"""Independent streams remain router-scoped even behind the same Docker NAT."""

from dataclasses import replace
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv4Network

import pytest
from sqlalchemy import select

from backend.app.bandwidth.contracts import FlowPolicy
from backend.app.bandwidth.discovery import build_inventory_snapshot
from backend.app.bandwidth.ingestion_config import IngestionPolicy
from backend.app.bandwidth.spool import SpoolError, source_manifest
from backend.app.models.bandwidth_ingestion import BandwidthFlow
from backend.app.services.bandwidth_ingestion_service import ingest_segment
from backend.app.services.bandwidth_inventory_service import sync_inventory
from backend.app.services.bandwidth_query_service import list_clients, query_usage
from tests.bandwidth_fixtures import START, record, sealed
from tests.test_utils import run


def test_two_routers_share_nat_and_client_addresses_without_merging(inventory_sessions, tmp_path):
    policy = IngestionPolicy(
        FlowPolicy(1, frozenset({11}), frozenset({2}), (IPv4Network("192.168.88.0/24"),), ()),
        IPv4Address("192.168.65.1"),
    )
    day = datetime.fromtimestamp(START // 10**9, UTC).date()
    mac = "02:00:00:00:00:10"

    async def exercise():
        client_ids = []
        for router_id, count in ((1, 100), (2, 250)):
            directory = tmp_path / str(router_id)
            directory.mkdir()
            source = source_manifest(directory, router_id=router_id)
            current_policy = replace(policy, flow=replace(policy.flow, router_id=router_id))
            lease = {
                "address": "192.168.88.10",
                "mac-address": mac,
                "status": "bound",
                "host-name": f"Site {router_id}",
            }
            async with inventory_sessions.begin() as db:
                await sync_inventory(db, build_inventory_snapshot(router_id, START - 100, [lease], []))
                await sync_inventory(db, build_inventory_snapshot(router_id, START + 100, [lease], []))
            payload = record(sampler_address="192.168.65.1", src_addr="192.168.88.10", in_if=11, out_if=2, bytes=count)
            segment = sealed(directory, payload)
            async with inventory_sessions.begin() as db:
                report = await ingest_segment(db, source, segment, payload, current_policy)
                assert report.accepted == 1
            with pytest.raises(SpoolError, match="source_router_mismatch"):
                async with inventory_sessions.begin() as db:
                    await ingest_segment(
                        db,
                        source,
                        segment,
                        payload,
                        replace(current_policy, flow=replace(policy.flow, router_id=3 - router_id)),
                    )
            async with inventory_sessions() as db:
                clients = await list_clients(db, router_id, 50, 0)
                assert len(clients.items) == 1
                assert clients.items[0].hostname == f"Site {router_id}"
                client_ids.append(clients.items[0].id)
                page = await query_usage(db, router_id, day, day, top=True)
                assert len(page.items) == 1 and page.items[0].total_bytes == str(count)
                assert page.items[0].client_id == client_ids[-1]
        assert len(set(client_ids)) == 2
        async with inventory_sessions() as db:
            rows = list(await db.scalars(select(BandwidthFlow)))
            assert {row.router_id for row in rows} == {1, 2}
            assert {row.byte_count for row in rows} == {100, 250}

    run(exercise())
