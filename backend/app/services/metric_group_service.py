"""Bounded group read model, separate from individual-device dashboard context."""

from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.schemas.dashboard import MetricHistoryItem, MetricHistorySection, MetricPayloadMeta
from ..api.schemas.metric_group import GroupDeviceHealth, MetricGroupMeta, MetricGroupPayload
from ..core.config import settings
from ..core.time import WIB, now
from ..repositories.metric_group_repository import VALUE_CHAR_LIMIT, MetricGroupRepository
from ..repositories.metric_repository import MetricRepository
from .observability_service import record_api_payload_request, record_api_payload_section

MAX_TREND_ITEMS = 2000
MAX_PAYLOAD_BYTES = 1_048_576


def section(
    items: list[dict], *, limit: int, total: int | None = None, offset: int = 0, sampled: bool = False
) -> MetricHistorySection:
    return MetricHistorySection(
        items=[MetricHistoryItem(**item) for item in items],
        meta=MetricPayloadMeta(
            total=len(items) if total is None else total, limit=limit, offset=offset, sampled=sampled
        ),
    )


async def get_metric_group(
    db: AsyncSession,
    *,
    group: str,
    mode: str,
    site: str | None = None,
    device_type: str | None = None,
    device_id: int | None = None,
    metric_name: str | None = None,
    status: str | None = None,
    checked_from: datetime | None = None,
    checked_to: datetime | None = None,
    device_limit: int = 20,
    device_offset: int = 0,
    samples_per_series: int = 50,
    snapshot_limit: int = 10,
    snapshot_offset: int = 0,
) -> MetricGroupPayload:
    generated = now()
    if mode == "live":
        checked_from, checked_to = generated - timedelta(hours=24), generated
    elif checked_from is None or checked_to is None:
        raise HTTPException(422, "Rentang tanggal harus memiliki waktu mulai dan akhir.")
    else:
        checked_from = checked_from.astimezone(WIB).replace(tzinfo=None) if checked_from.tzinfo else checked_from
        checked_to = checked_to.astimezone(WIB).replace(tzinfo=None) if checked_to.tzinfo else checked_to
    if checked_from > checked_to or checked_to - checked_from > timedelta(days=31):
        raise HTTPException(422, "Rentang tanggal harus berurutan dan maksimal 31 hari.")
    repository = MetricGroupRepository(db)
    devices, total = await repository.devices(
        group=group, site=site, device_type=device_type, device_id=device_id, limit=device_limit, offset=device_offset
    )
    ids = [device.id for device in devices]
    names = await repository.metric_names(ids) if ids else []
    chart_names = [metric_name] if metric_name else names[:8]
    samples = min(samples_per_series, MAX_TREND_ITEMS // max(len(ids) * len(chart_names), 1))
    trend, trend_sampled = (
        await repository.trends(
            device_ids=ids,
            metric_names=chart_names,
            status=status,
            checked_from=checked_from,
            checked_to=checked_to,
            samples=samples,
        )
        if ids and chart_names
        else ([], False)
    )
    trend_sampled = trend_sampled or (not metric_name and len(names) > 8)
    history, _, history_sampled = (
        await repository.section(
            device_ids=ids,
            metric_name=metric_name,
            status=status,
            checked_from=checked_from,
            checked_to=checked_to,
            snapshot=False,
            limit=100,
        )
        if ids
        else ([], 0, False)
    )
    snapshots, snapshot_total, _ = (
        await repository.section(
            device_ids=ids,
            metric_name=metric_name,
            status=status,
            checked_from=checked_from,
            checked_to=checked_to,
            snapshot=True,
            limit=snapshot_limit,
            offset=snapshot_offset,
        )
        if ids
        else ([], 0, False)
    )
    health = await repository.health(ids) if ids else {}
    age = max(60, settings.scheduler.interval_device_seconds * max(settings.scheduler.job_stale_factor, 1))
    device_health = []
    statuses: dict[str, int] = {}
    for device in devices:
        timestamp, state = health.get(device.id, (None, "unknown"))
        freshness = (
            "no_data" if timestamp is None else "stale" if timestamp <= generated - timedelta(seconds=age) else "fresh"
        )
        device_health.append(
            GroupDeviceHealth(
                id=device.id,
                name=device.name,
                site=device.site,
                device_type=device.device_type,
                latest_checked_at=timestamp,
                status=state,
                freshness=freshness,
            )
        )
        statuses[state] = statuses.get(state, 0) + 1
    empty = section([], limit=0)
    result = MetricGroupPayload(
        metric_names=names[:64],
        history=section(history, limit=100, sampled=history_sampled),
        selected_device_history=empty,
        selected_device_trend=section(trend, limit=MAX_TREND_ITEMS, sampled=trend_sampled),
        selected_device_snapshot=empty,
        latest_snapshot=section(
            snapshots,
            limit=snapshot_limit,
            total=snapshot_total,
            offset=snapshot_offset,
            sampled=snapshot_total > len(snapshots),
        ),
        latest_snapshot_status_summary=statuses,
        snapshot_uptime_map=await MetricRepository(db).latest_snapshot_uptime_map_for_rows(snapshots),
        group=MetricGroupMeta(
            total_devices=total,
            device_limit=device_limit,
            device_offset=device_offset,
            has_more_devices=device_offset + len(devices) < total,
            devices=device_health,
            generated_at=generated,
            checked_from=checked_from,
            checked_to=checked_to,
            series_metric_names=chart_names,
            metric_names_truncated=len(names) > 64,
            samples_per_series=samples,
            max_trend_items=MAX_TREND_ITEMS,
            max_payload_bytes=MAX_PAYLOAD_BYTES,
            value_char_limit=VALUE_CHAR_LIMIT,
            trend_sampled=trend_sampled,
        ),
    )
    # Reduce every series fairly, retaining its newest points, if Unicode/text
    # fields make the serialized response exceed the byte budget.
    while len(result.model_dump_json().encode()) > MAX_PAYLOAD_BYTES and result.selected_device_trend.items:
        samples //= 2
        counts: dict[tuple[int, str], int] = {}
        kept = []
        for item in trend:
            key = (item["device_id"], item["metric_name"])
            counts[key] = counts.get(key, 0) + 1
            if counts[key] <= samples:
                kept.append(item)
        result.selected_device_trend = section(kept, limit=MAX_TREND_ITEMS, sampled=True)
        result.group.samples_per_series = samples
        result.group.trend_sampled = True
    if len(result.model_dump_json().encode()) > MAX_PAYLOAD_BYTES:
        raise HTTPException(413, "Respons grup terlalu besar; pilih metrik atau halaman yang lebih kecil.")
    endpoint, scope = "/metrics/history/group", f"group:{group}"
    record_api_payload_request(endpoint=endpoint, scope=scope)
    for name, payload in (
        ("history", result.history),
        ("selected_device_trend", result.selected_device_trend),
        ("latest_snapshot", result.latest_snapshot),
    ):
        record_api_payload_section(
            endpoint=endpoint,
            scope=scope,
            section=name,
            rows=len(payload.items),
            total_rows=payload.meta.total,
            sampled=bool(payload.meta.sampled),
        )
    return result
