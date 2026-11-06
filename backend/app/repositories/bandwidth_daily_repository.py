"""Batch daily increments; caller holds the ingestion router lock."""

from collections import defaultdict
from time import time_ns
from typing import cast

from sqlalchemy import Table
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..bandwidth.contracts import ClassifiedFlow
from ..bandwidth.daily import allocate_days
from ..models.bandwidth_daily import BandwidthDailyUsage


async def increment_daily_usage(db: AsyncSession, flows: list[tuple[ClassifiedFlow, int | None]]) -> None:
    buckets: dict[tuple, list[int]] = defaultdict(lambda: [0, 0, 0])
    now = time_ns()
    for item, client_id in flows:
        subject = f"c:{client_id}" if client_id is not None else f"ip:{item.device_ip}"
        for day, count, estimated in allocate_days(item.flow.started_ns, item.flow.ended_ns, item.flow.bytes):
            if count:
                key = (item.router_id, day, subject, client_id, None if client_id else str(item.device_ip))
                totals = buckets[key]
                totals[0 if item.direction.value == "upload" else 1] += count
                totals[2] += count if estimated else 0
                if len(buckets) >= 1000:
                    await increment_daily_buckets(db, buckets, now)
                    buckets.clear()
    await increment_daily_buckets(db, buckets, now)


async def increment_daily_buckets(db: AsyncSession, buckets: dict[tuple, list[int]], now: int) -> None:
    dialect = db.get_bind().dialect.name
    if dialect not in {"mysql", "sqlite"}:
        raise ValueError("Unsupported bandwidth database dialect")
    table = cast(Table, BandwidthDailyUsage.__table__)
    values = [
        dict(
            router_id=key[0],
            day=key[1],
            subject=key[2],
            client_id=key[3],
            unresolved_ip=key[4],
            upload_bytes=counts[0],
            download_bytes=counts[1],
            estimated_bytes=counts[2],
            updated_ns=now,
        )
        for key, counts in sorted(buckets.items())
    ]
    for index in range(0, len(values), 100):
        chunk = values[index : index + 100]
        if dialect == "mysql":
            statement = mysql_insert(table).values(chunk)
            await db.execute(
                statement.on_duplicate_key_update(
                    upload_bytes=table.c.upload_bytes + statement.inserted.upload_bytes,
                    download_bytes=table.c.download_bytes + statement.inserted.download_bytes,
                    estimated_bytes=table.c.estimated_bytes + statement.inserted.estimated_bytes,
                    updated_ns=statement.inserted.updated_ns,
                )
            )
        else:
            statement_sqlite = sqlite_insert(table).values(chunk)
            await db.execute(
                statement_sqlite.on_conflict_do_update(
                    index_elements=["router_id", "day", "subject"],
                    set_={
                        "upload_bytes": table.c.upload_bytes + statement_sqlite.excluded.upload_bytes,
                        "download_bytes": table.c.download_bytes + statement_sqlite.excluded.download_bytes,
                        "estimated_bytes": table.c.estimated_bytes + statement_sqlite.excluded.estimated_bytes,
                        "updated_ns": statement_sqlite.excluded.updated_ns,
                    },
                )
            )
