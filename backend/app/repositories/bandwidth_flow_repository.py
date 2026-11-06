"""Current-value checkpoint locking and batched identity lookup for flow ingestion."""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..bandwidth.contracts import ClassifiedFlow
from ..models.bandwidth import BandwidthIPHistory
from ..models.bandwidth_ingestion import BandwidthFlowStream
from ..models.device import Device


class BandwidthFlowRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def lock_stream(self, stream_id: str, router_id: int, digest: str, now_ns: int) -> BandwidthFlowStream:
        # Parent lock also serializes the first creation; a missing stream cannot
        # otherwise be reliably row-locked on every supported SQL dialect.
        router = await self.db.scalar(select(Device.id).where(Device.id == router_id).with_for_update())
        if router is None:
            raise ValueError("ingestion_router_missing")
        rows = await self.db.scalars(
            select(BandwidthFlowStream)
            .where(BandwidthFlowStream.stream_id == stream_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        stream = rows.one_or_none()
        if stream is None:
            stream = BandwidthFlowStream(
                stream_id=stream_id,
                router_id=router_id,
                policy_digest=digest,
                heartbeat_ns=now_ns,
                status="idle",
            )
            self.db.add(stream)
            await self.db.flush()
        if stream.router_id != router_id or stream.policy_digest != digest:
            raise ValueError("ingestion_policy_changed")
        return stream

    async def resolve_clients(self, flows: list[ClassifiedFlow]) -> list[int | None]:
        """One bounded query per IP chunk, not one query per flow.

        Missing or ambiguous coverage stays NULL. A pathological number of
        historical intervals also stays unresolved rather than growing memory
        without a limit; later reconciliation can inspect those rows explicitly.
        """
        if not flows:
            return []
        router_id = flows[0].router_id
        addresses = sorted({str(flow.device_ip) for flow in flows})
        first = min(flow.flow.started_ns for flow in flows)
        last = max(flow.flow.ended_ns for flow in flows)
        histories: dict[str, list[BandwidthIPHistory]] = defaultdict(list)
        for index in range(0, len(addresses), 500):
            chunk = addresses[index : index + 500]
            rows = list(
                (
                    await self.db.scalars(
                        select(BandwidthIPHistory)
                        .where(
                            BandwidthIPHistory.router_id == router_id,
                            BandwidthIPHistory.ip_address.in_(chunk),
                            BandwidthIPHistory.first_observed_ns <= last,
                            BandwidthIPHistory.last_observed_ns >= first,
                        )
                        .with_for_update()
                        .limit(10001)
                    )
                ).all()
            )
            if len(rows) > 10000:
                continue
            for row in rows:
                histories[row.ip_address].append(row)
        result: list[int | None] = []
        for flow in flows:
            owners = [
                row.client_id
                for row in histories[str(flow.device_ip)]
                if row.first_observed_ns <= flow.flow.started_ns and row.last_observed_ns >= flow.flow.ended_ns
            ]
            result.append(owners[0] if len(owners) == 1 else None)
        return result
