"""Bounded reporting queries against daily summaries, never the raw flow log."""

from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.schemas.bandwidth import ClientPage, ClientRow, IdentityObservation, UsagePage, UsageRow
from ..models.bandwidth import BandwidthClient, BandwidthIPHistory
from ..models.bandwidth_daily import BandwidthDailyUsage as Daily
from ..models.device import Device


async def require_router(db: AsyncSession, router_id: int) -> None:
    if await db.scalar(select(Device.id).where(Device.id == router_id, Device.device_type == "mikrotik")) is None:
        raise HTTPException(404, "MikroTik router not found")


async def list_clients(db: AsyncSession, router_id: int, limit: int, after_id: int) -> ClientPage:
    if not 1 <= limit <= 200 or after_id < 0:
        raise HTTPException(422, "Invalid client pagination")
    await require_router(db, router_id)
    clients = list(
        await db.scalars(
            select(BandwidthClient)
            .where(
                BandwidthClient.router_id == router_id,
                BandwidthClient.id > after_id,
            )
            .order_by(BandwidthClient.id)
            .limit(limit + 1)
        )
    )
    return ClientPage(
        items=[
            ClientRow(
                id=client.id,
                mac_address=client.mac_address,
                hostname=client.hostname,
                custom_name=client.custom_name,
                display_name=client.custom_name or client.hostname or client.mac_address,
                first_seen_ns=str(client.first_seen_ns),
                last_seen_ns=str(client.last_seen_ns),
            )
            for client in clients[:limit]
        ],
        next_after_id=clients[limit - 1].id if len(clients) > limit else None,
    )


async def query_usage(
    db: AsyncSession,
    router_id: int,
    start: date,
    end: date,
    *,
    top: bool = False,
    client_id: int | None = None,
    limit: int = 31,
    offset: int = 0,
) -> UsagePage:
    if end < start or (end - start).days >= 31:
        raise HTTPException(422, "Date range must contain 1 to 31 inclusive calendar days")
    if not 1 <= limit <= 200 or not 0 <= offset <= 10000:
        raise HTTPException(422, "Invalid report pagination")
    await require_router(db, router_id)
    if (
        client_id is not None
        and await db.scalar(
            select(BandwidthClient.id).where(
                BandwidthClient.router_id == router_id,
                BandwidthClient.id == client_id,
            )
        )
        is None
    ):
        raise HTTPException(404, "Bandwidth client not found for router")
    upload, download = func.sum(Daily.upload_bytes), func.sum(Daily.download_bytes)
    columns: list[Any] = [
        upload.label("upload"),
        download.label("download"),
        func.sum(Daily.estimated_bytes).label("estimated"),
        func.sum(case((Daily.client_id.is_(None), Daily.upload_bytes + Daily.download_bytes), else_=0)).label(
            "unresolved"
        ),
        func.max(Daily.updated_ns).label("updated"),
    ]
    if top:
        columns += [
            Daily.subject,
            Daily.client_id,
            Daily.unresolved_ip,
            BandwidthClient.custom_name,
            BandwidthClient.hostname,
            BandwidthClient.mac_address,
        ]
    else:
        columns += [Daily.day]
    statement = (
        select(*columns)
        .select_from(Daily)
        .where(
            Daily.router_id == router_id,
            Daily.day >= start,
            Daily.day <= end,
        )
    )
    if client_id is not None:
        statement = statement.where(Daily.subject == f"c:{client_id}")
    if top:
        statement = (
            statement.outerjoin(
                BandwidthClient,
                ((BandwidthClient.id == Daily.client_id) & (BandwidthClient.router_id == Daily.router_id)),
            )
            .group_by(
                Daily.subject,
                Daily.client_id,
                Daily.unresolved_ip,
                BandwidthClient.custom_name,
                BandwidthClient.hostname,
                BandwidthClient.mac_address,
            )
            .order_by(
                (upload + download).desc(),
                Daily.subject,
            )
        )
    else:
        statement = statement.group_by(Daily.day).order_by(Daily.day)
    rows = (await db.execute(statement.limit(limit + 1).offset(offset))).mappings().all()
    observations = {}
    if top:
        addresses = {row["unresolved_ip"] for row in rows[:limit] if row["unresolved_ip"]}
        if addresses:
            # A current observation is only a display hint for legacy IP rows.
            # It never changes their owner, filter target or unresolved bytes.
            observed = await db.execute(
                select(BandwidthIPHistory, BandwidthClient)
                .join(
                    BandwidthClient,
                    (BandwidthClient.id == BandwidthIPHistory.client_id)
                    & (BandwidthClient.router_id == BandwidthIPHistory.router_id),
                )
                .where(
                    BandwidthIPHistory.router_id == router_id,
                    BandwidthIPHistory.ip_address.in_(addresses),
                    BandwidthIPHistory.active_slot == 1,
                )
                .limit(limit)
            )
            observations = {
                history.ip_address: IdentityObservation(
                    display_name=client.custom_name or client.hostname or client.mac_address,
                    mac_address=client.mac_address,
                    observed_ns=str(history.last_observed_ns),
                )
                for history, client in observed
            }
    items = []
    for row in rows[:limit]:
        up, down = int(row["upload"]), int(row["download"])
        items.append(
            UsageRow(
                day=None if top else row["day"],
                subject=row["subject"] if top else None,
                client_id=row["client_id"] if top else None,
                unresolved_ip=row["unresolved_ip"] if top else None,
                display_name=(row["custom_name"] or row["hostname"] or row["mac_address"] or row["unresolved_ip"])
                if top
                else None,
                latest_observation=observations.get(row["unresolved_ip"]) if top else None,
                upload_bytes=str(up),
                download_bytes=str(down),
                total_bytes=str(up + down),
                estimated_bytes=str(int(row["estimated"])),
                unresolved_bytes=str(int(row["unresolved"])),
                updated_ns=str(row["updated"]),
            )
        )
    return UsagePage(
        router_id=router_id, start=start, end=end, items=items, limit=limit, offset=offset, has_more=len(rows) > limit
    )
