"""Shared helpers for metric repository mixins."""

from datetime import datetime
from typing import Any

from shared.number_utils import safe_float
from sqlalchemy import select
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.device import Device
from ...models.metric import Metric


class MetricRepositoryBase:
    """Shared database session and row-shaping helpers for metric repositories."""
    def __init__(self, db: AsyncSession) -> None:
        """Initialize the object with its runtime dependencies."""
        self.db = db

    @staticmethod
    def _metric_row_payload(row: Any) -> dict[str, Any]:
        """Convert a metric query row into the API response dictionary shape."""
        metric_value_numeric = row.metric_value_numeric
        if metric_value_numeric is None:
            metric_value_numeric = safe_float(row.metric_value)
        payload = {
            "id": row.id,
            "device_id": row.device_id,
            "device_name": row.device_name or "Unknown Device",
            "metric_name": row.metric_name,
            "metric_value": row.metric_value,
            "metric_value_numeric": metric_value_numeric,
            "status": row.status,
            "unit": row.unit,
            "checked_at": row.checked_at,
        }
        row_mapping = getattr(row, "_mapping", {})
        for key in (
            "sort_device_type_priority",
            "sort_internet_target_name_priority",
            "sort_device_name",
            "sort_metric_name",
        ):
            if key in row_mapping:
                payload[f"_{key}"] = row_mapping[key]
        return payload

    @staticmethod
    def _normalize_metric_names(metric_names: list[str] | None) -> list[str]:
        """Deduplicate requested metric names while preserving client order."""
        if not metric_names:
            return []
        return list(dict.fromkeys(str(metric_name) for metric_name in metric_names if metric_name))

    @staticmethod
    def _recent_metric_filter_conditions(
        *,
        device_id: int | None = None,
        metric_name: str | None = None,
        metric_names: list[str] | None = None,
        status: str | None = None,
        checked_from: datetime | None = None,
        checked_to: datetime | None = None,
    ) -> list[ColumnElement[bool]]:
        """Build SQLAlchemy filters shared by metric history queries."""
        conditions: list[ColumnElement[bool]] = []
        if device_id is not None:
            conditions.append(Metric.device_id == device_id)
        if metric_name:
            conditions.append(Metric.metric_name == metric_name)
        elif metric_names:
            normalized_metric_names = MetricRepositoryBase._normalize_metric_names(metric_names)
            if normalized_metric_names:
                conditions.append(Metric.metric_name.in_(normalized_metric_names))
        if status:
            conditions.append(Metric.status == status)
        if checked_from is not None:
            conditions.append(Metric.checked_at >= checked_from)
        if checked_to is not None:
            conditions.append(Metric.checked_at <= checked_to)
        return conditions

    def _recent_metric_rows_query(
        self,
        *,
        device_id: int | None = None,
        metric_name: str | None = None,
        metric_names: list[str] | None = None,
        status: str | None = None,
        checked_from: datetime | None = None,
        checked_to: datetime | None = None,
    ) -> Select[Any]:
        """Build the base joined query for metric history rows."""
        query = (
            select(
                Metric.id,
                Metric.device_id,
                Device.name.label("device_name"),
                Metric.metric_name,
                Metric.metric_value,
                Metric.metric_value_numeric,
                Metric.status,
                Metric.unit,
                Metric.checked_at,
            )
            .outerjoin(Device, Device.id == Metric.device_id)
        )
        conditions = self._recent_metric_filter_conditions(
            device_id=device_id,
            metric_name=metric_name,
            metric_names=metric_names,
            status=status,
            checked_from=checked_from,
            checked_to=checked_to,
        )
        if conditions:
            query = query.where(*conditions)
        return query
