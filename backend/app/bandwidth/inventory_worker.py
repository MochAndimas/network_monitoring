"""Optional single-router DHCP/ARP inventory polling, without alert evaluation."""

import argparse
import asyncio
import logging
import math
import signal
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from time import time_ns

from librouteros import connect
from sqlalchemy import select

from ..core.config import configure_logging, settings
from ..core.settings_groups import MikrotikSettings
from ..db.session import SessionLocal, engine
from ..models.bandwidth import BandwidthInventoryState
from ..models.device import Device
from ..services.bandwidth_inventory_service import sync_inventory
from ..services.bandwidth_reconciliation_service import ReconciliationCursor, reconcile_identities
from .discovery import InventorySnapshot, build_inventory_snapshot
from .health import observation_is_fresh
from .ingestion_config import load_policy

logger = logging.getLogger(__name__)


def read_snapshot(
    router_id: int, target: MikrotikSettings, api_host: str, expected_identity: str = ""
) -> InventorySnapshot:
    """Publish nothing unless both complete API reads succeed. Always close API."""
    api = connect(host=api_host, port=target.port, username=target.username, password=target.password, timeout=10)
    try:
        if expected_identity:
            identities = list(api.path("system", "identity"))
            if len(identities) != 1 or identities[0].get("name") != expected_identity:
                raise ValueError("inventory_router_identity_mismatch")
        leases = list(api.path("ip", "dhcp-server", "lease"))
        arp = list(api.path("ip", "arp"))
        return build_inventory_snapshot(router_id, time_ns(), leases, arp)
    finally:
        api.close()


async def validate_binding(sessions, router_id: int, target: MikrotikSettings) -> None:
    async with sessions() as db:
        matched = await db.scalar(
            select(Device.id).where(
                Device.id == router_id,
                Device.device_type == "mikrotik",
                Device.ip_address == target.host,
            )
        )
    if matched is None:
        raise ValueError("inventory_target_router_mismatch")


async def poll_once(
    sessions,
    router_id: int,
    target: MikrotikSettings,
    api_host: str,
    max_gap: int,
    *,
    fallback_host: str = "",
    expected_identity: str = "",
    api_port: int | None = None,
    fallback_port: int | None = None,
    reconciliation_cursor: ReconciliationCursor | None = None,
) -> str:
    await validate_binding(sessions, router_id, target)
    # Retry the preferred endpoint on every poll: VPN reconnects recover without
    # sticky LAN selection, process restarts, or partial observations.
    endpoints = tuple(
        dict.fromkeys(
            (host, port or target.port) for host, port in ((api_host, api_port), (fallback_host, fallback_port)) if host
        )
    )
    if fallback_host and not expected_identity:
        raise ValueError("inventory_fallback_requires_router_identity")
    for index, (host, port) in enumerate(endpoints):
        try:
            snapshot = await asyncio.to_thread(
                read_snapshot, router_id, replace(target, port=port), host, expected_identity
            )
            break
        except Exception:
            if index == len(endpoints) - 1:
                raise
            logger.warning("Preferred inventory endpoint unavailable router_id=%s; trying fallback", router_id)
    else:
        raise ValueError("inventory_requires_api_host")
    async with sessions.begin() as db:
        await sync_inventory(db, snapshot, max_observation_gap_seconds=max_gap)
    # Bound each transaction and release the router lock between batches so live
    # ingestion can progress. Later polls drain any remaining historical backlog.
    reconciled = 0
    cursor = reconciliation_cursor if reconciliation_cursor is not None else ReconciliationCursor()
    for _ in range(10):
        next_cursor = replace(cursor)
        async with sessions.begin() as db:
            moved = await reconcile_identities(db, router_id, cursor=next_cursor)
        # Only advance after commit: a failed batch must be retried.
        cursor.after_id, cursor.upper_id = next_cursor.after_id, next_cursor.upper_id
        reconciled += moved
        if cursor.upper_id is None:
            break
    logger.info("Inventory snapshot committed router_id=%s clients=%s", router_id, len(snapshot.clients))
    logger.info("Inventory identities reconciled router_id=%s flows=%s", router_id, reconciled)
    return host


async def snapshot_fresh(sessions, router_id: int, max_gap: int) -> bool:
    async with sessions() as db:
        observed = await db.scalar(
            select(BandwidthInventoryState.observed_ns).where(BandwidthInventoryState.router_id == router_id)
        )
    return observed is not None and observation_is_fresh(observed, time_ns(), max_gap)


async def run(args: argparse.Namespace) -> None:
    try:
        if not settings.bandwidth_inventory_enabled or not settings.bandwidth_flow_policy_file:
            raise ValueError("inventory_requires_enablement_and_policy")
        max_gap = settings.bandwidth_inventory_max_gap_seconds
        if not math.isfinite(args.poll_seconds) or not 0 < args.poll_seconds <= max_gap / 2:
            raise ValueError("inventory_poll_must_fit_observation_gap")
        if any(port is not None and not 1 <= port <= 65535 for port in (args.api_port, args.fallback_port)):
            raise ValueError("inventory_api_port_out_of_range")
        policy = load_policy(Path(settings.bandwidth_flow_policy_file))
        target = next(t for t in settings.configured_mikrotik_targets if t.name == args.target_name)
        router_id = policy.flow.router_id
        if args.fallback_host and not args.router_identity:
            raise ValueError("inventory_fallback_requires_router_identity")
        await validate_binding(SessionLocal, router_id, target)
        if args.command == "health":
            if not await snapshot_fresh(SessionLocal, router_id, max_gap):
                raise SystemExit(1)
            return
        if args.command == "once":
            await poll_once(
                SessionLocal,
                router_id,
                target,
                args.api_host or target.host,
                max_gap,
                fallback_host=args.fallback_host,
                expected_identity=args.router_identity,
                api_port=args.api_port,
                fallback_port=args.fallback_port,
            )
            return
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for number in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(number, stop.set)
        active_host = None
        reconciliation_cursor = ReconciliationCursor()
        while not stop.is_set():
            try:
                host = await poll_once(
                    SessionLocal,
                    router_id,
                    target,
                    args.api_host or target.host,
                    max_gap,
                    fallback_host=args.fallback_host,
                    expected_identity=args.router_identity,
                    api_port=args.api_port,
                    fallback_port=args.fallback_port,
                    reconciliation_cursor=reconciliation_cursor,
                )
                if host != active_host:
                    logger.info("Inventory connection selected router_id=%s api_host=%s", router_id, host)
                    active_host = host
            except Exception:
                # Connection errors may include credentials; log no exception text.
                logger.warning("Inventory poll failed router_id=%s; retaining last observation", router_id)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=args.poll_seconds)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "once", "health"), default="run", nargs="?")
    parser.add_argument("--target-name", default=settings.bandwidth_inventory_target_name)
    parser.add_argument("--api-host", default=settings.bandwidth_inventory_api_host)
    parser.add_argument("--api-port", type=int, default=settings.bandwidth_inventory_api_port)
    parser.add_argument("--fallback-host", default=settings.bandwidth_inventory_api_fallback_host)
    parser.add_argument("--fallback-port", type=int, default=settings.bandwidth_inventory_api_fallback_port)
    parser.add_argument("--router-identity", default=settings.bandwidth_inventory_router_identity)
    parser.add_argument("--poll-seconds", type=float, default=settings.bandwidth_inventory_poll_seconds)
    args = parser.parse_args()
    configure_logging()
    try:
        asyncio.run(run(args))
    except Exception:
        logger.error("Inventory worker stopped; check target binding, policy, API access and database")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
