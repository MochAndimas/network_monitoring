"""Read-only diagnostics and transfer observations; no raw record output."""

from ipaddress import IPv4Address
from time import time_ns

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..bandwidth.health import observation_is_fresh
from ..bandwidth.ingestion_config import IngestionPolicy
from ..bandwidth.validation import TransferBaseline
from ..models.bandwidth_ingestion import (
    BandwidthFlow,
    BandwidthFlowRejection,
    BandwidthFlowSegment,
    BandwidthFlowStream,
)


async def ingestion_status(db: AsyncSession, policy: IngestionPolicy) -> dict:
    now = time_ns()
    router_id = policy.flow.router_id
    streams = list(
        await db.scalars(select(BandwidthFlowStream).where(BandwidthFlowStream.router_id == router_id).limit(101))
    )
    if len(streams) > 100:
        raise ValueError("too_many_router_streams")
    states = []
    for stream in streams:
        age = now - stream.heartbeat_ns
        states.append(
            {
                "stream_id": stream.stream_id,
                "status": stream.status,
                "heartbeat_age_seconds": age // 10**9,
                "last_error_code": stream.last_error_code,
                "policy_matches": stream.policy_digest == policy.digest,
                "alive": stream.policy_digest == policy.digest
                and stream.status in {"running", "idle"}
                and observation_is_fresh(stream.heartbeat_ns, now),
            }
        )
    scoped_streams = select(BandwidthFlowStream.stream_id).where(BandwidthFlowStream.router_id == router_id)
    rejected = (
        await db.execute(
            select(BandwidthFlowRejection.reason, func.sum(BandwidthFlowRejection.record_count))
            .where(
                BandwidthFlowRejection.stream_id.in_(scoped_streams),
            )
            .group_by(BandwidthFlowRejection.reason)
        )
    ).all()
    # Durable checkpoint counters are much smaller than the raw flow history.
    # Keep this operator query out of a frequent HTTP/health polling path.
    accepted, pending = (
        await db.execute(
            select(
                func.coalesce(func.sum(BandwidthFlowSegment.accepted_count), 0),
                func.coalesce(func.sum(case((BandwidthFlowSegment.completed.is_(False), 1), else_=0)), 0),
            ).where(
                BandwidthFlowSegment.stream_id.in_(scoped_streams),
            )
        )
    ).one()
    last = None
    if accepted:
        last = (
            await db.execute(
                select(BandwidthFlow.id, BandwidthFlow.received_ns)
                .where(BandwidthFlow.router_id == router_id)
                .order_by(BandwidthFlow.id.desc())
                .limit(1)
            )
        ).one_or_none()
    return {
        "router_id": router_id,
        "policy_digest": policy.digest,
        "checked_ns": str(now),
        "worker_alive": any(state["alive"] for state in states),
        "streams": states,
        "accepted_flows": str(int(accepted)),
        "last_flow_received_ns": str(last.received_ns) if last else None,
        "last_flow_id": str(last.id) if last else "0",
        "pending_segments": int(pending or 0),
        "rejected_records": {reason: str(int(count)) for reason, count in rejected},
        "completeness": "unverified",
        "counter_scope": "all_router_streams",
    }


async def capture_baseline(db: AsyncSession, policy: IngestionPolicy, device_ip: str) -> TransferBaseline:
    address = IPv4Address(device_ip)
    if not any(address in network for network in policy.flow.lan_networks):
        raise ValueError("device_outside_policy")
    status = await ingestion_status(db, policy)
    if not status["worker_alive"]:
        raise ValueError("matching_worker_not_alive")
    return TransferBaseline(policy.flow.router_id, policy.digest, str(address), str(time_ns()), status["last_flow_id"])


async def observe_transfer(db: AsyncSession, policy: IngestionPolicy, baseline: TransferBaseline) -> dict:
    if baseline.router_id != policy.flow.router_id or baseline.policy_digest != policy.digest:
        raise ValueError("baseline_policy_mismatch")
    upload, download, count, preexisting = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(case((BandwidthFlow.direction == "upload", BandwidthFlow.byte_count), else_=0)), 0
                ),
                func.coalesce(
                    func.sum(case((BandwidthFlow.direction == "download", BandwidthFlow.byte_count), else_=0)), 0
                ),
                func.count(),
                func.coalesce(func.sum(case((BandwidthFlow.started_ns < int(baseline.created_ns), 1), else_=0)), 0),
            ).where(
                BandwidthFlow.router_id == baseline.router_id,
                BandwidthFlow.device_ip == baseline.device_ip,
                BandwidthFlow.id > int(baseline.last_flow_id),
                BandwidthFlow.stream_id.in_(
                    select(BandwidthFlowStream.stream_id).where(
                        BandwidthFlowStream.router_id == baseline.router_id,
                        BandwidthFlowStream.policy_digest == baseline.policy_digest,
                    )
                ),
            )
        )
    ).one()
    return {
        "upload": int(upload),
        "download": int(download),
        "flow_count": int(count),
        "flows_started_before_baseline": int(preexisting),
    }
