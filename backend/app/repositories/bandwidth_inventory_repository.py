"""Bounded inventory queries; transaction and router lock belong to the caller."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.bandwidth import BandwidthClient, BandwidthInventoryState, BandwidthIPHistory
from ..models.device import Device


class BandwidthInventoryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def lock_router(self, router_id: int) -> Device:
        router = await self.db.scalar(select(Device).where(Device.id == router_id).with_for_update())
        if router is None:
            raise ValueError("Inventory router does not exist")
        return router

    async def state(self, router_id: int) -> BandwidthInventoryState | None:
        # Locking reads see current data even if MySQL's REPEATABLE READ snapshot
        # was established by metric reads before the router lock was acquired.
        result = await self.db.scalars(
            select(BandwidthInventoryState)
            .where(BandwidthInventoryState.router_id == router_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.one_or_none()

    async def clients_by_mac(self, router_id: int, macs: set[str]) -> dict[str, BandwidthClient]:
        result: dict[str, BandwidthClient] = {}
        ordered = sorted(macs)
        for start in range(0, len(ordered), 500):
            clients = await self.db.scalars(
                select(BandwidthClient)
                .where(
                    BandwidthClient.router_id == router_id,
                    BandwidthClient.mac_address.in_(ordered[start : start + 500]),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            result.update((client.mac_address, client) for client in clients)
        return result

    async def active_bindings(self, router_id: int) -> list[BandwidthIPHistory]:
        return list(
            (
                await self.db.scalars(
                    select(BandwidthIPHistory)
                    .where(BandwidthIPHistory.router_id == router_id, BandwidthIPHistory.active_slot == 1)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )

    async def resolve_client(self, router_id: int, ip: str, start_ns: int, end_ns: int) -> int | None:
        """Resolve only a flow fully covered by one observed interval.

        This deliberately leaves transfers before the first observation, during
        gaps, or across ownership changes unattributed for later reconciliation.
        """
        if start_ns <= 0 or end_ns < start_ns:
            raise ValueError("Invalid flow interval")
        owners = list(
            (
                await self.db.scalars(
                    select(BandwidthIPHistory.client_id)
                    .where(
                        BandwidthIPHistory.router_id == router_id,
                        BandwidthIPHistory.ip_address == ip,
                        BandwidthIPHistory.first_observed_ns <= start_ns,
                        BandwidthIPHistory.last_observed_ns >= end_ns,
                    )
                    .limit(2)
                )
            ).all()
        )
        return owners[0] if len(owners) == 1 else None
