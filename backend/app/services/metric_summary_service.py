"""Metric summary service: focused metric/alert workflow responsibilities."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from ..api.schemas import (
    MetricColdArchiveItem,
    MetricColdArchivePage,
    MetricDailySummaryItem,
    MetricDailySummaryPage,
    MetricLongTermExplorerPayload,
    MetricSiteTypeTrendItem,
    PageMeta,
)
from ..repositories.metric_repository import MetricRepository
from .metric_read_payloads import _record_payload_section
from .observability_service import record_api_payload_request, record_api_payload_section


async def get_metrics_daily_summary(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    device_id: int | None = None,
    site: str | None = None,
    device_type: str | None = None,
    rollup_from: date | None = None,
    rollup_to: date | None = None,
) -> MetricDailySummaryPage:
    """Return paginated daily metric rollup rows."""
    rows, total = await MetricRepository(db).list_daily_summary_rows_paged(
        limit=limit,
        offset=offset,
        device_id=device_id,
        site=site,
        device_type=device_type,
        rollup_from=rollup_from,
        rollup_to=rollup_to,
    )
    _record_payload_section(
        endpoint="/metrics/daily-summary",
        device_id=device_id,
        section="items",
        rows=len(rows),
        total_rows=total,
        sampled=total > len(rows),
    )
    return MetricDailySummaryPage(
        items=[MetricDailySummaryItem(**row) for row in rows],
        meta=PageMeta(total=total, limit=limit, offset=offset),
    )


async def get_metrics_long_term_explorer(
    db: AsyncSession,
    *,
    archive_from: date | None,
    archive_to: date | None,
    metric_name: str | None,
    site: str | None,
    device_type: str | None,
    limit: int,
    offset: int,
) -> MetricLongTermExplorerPayload:
    """Return long-term trend and cold archive rows without scanning raw metrics."""
    repository = MetricRepository(db)
    trends = await repository.list_long_term_trend_rows(
        rollup_from=archive_from,
        rollup_to=archive_to,
        site=site,
        device_type=device_type,
        limit=366,
    )
    archive_rows, total = await repository.list_cold_archive_rows(
        archive_from=archive_from,
        archive_to=archive_to,
        metric_name=metric_name,
        site=site,
        device_type=device_type,
        limit=limit,
        offset=offset,
    )
    record_api_payload_request(endpoint="/metrics/long-term-explorer", scope="archive")
    record_api_payload_section(
        endpoint="/metrics/long-term-explorer",
        scope="archive",
        section="trends",
        rows=len(trends),
        total_rows=len(trends),
        sampled=False,
    )
    record_api_payload_section(
        endpoint="/metrics/long-term-explorer",
        scope="archive",
        section="archives",
        rows=len(archive_rows),
        total_rows=total,
        sampled=total > len(archive_rows),
    )
    return MetricLongTermExplorerPayload(
        trends=[MetricSiteTypeTrendItem(**row) for row in trends],
        archives=MetricColdArchivePage(
            items=[MetricColdArchiveItem(**row) for row in archive_rows],
            meta=PageMeta(total=total, limit=limit, offset=offset),
        ),
    )
