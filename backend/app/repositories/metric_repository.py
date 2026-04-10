from collections.abc import Iterable

from sqlalchemy import Select, desc, distinct, select
from sqlalchemy.orm import Session

from ..models.metric import Metric


class MetricRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_metrics(self, payloads: Iterable[dict]) -> list[Metric]:
        metrics = [Metric(**payload) for payload in payloads]
        if not metrics:
            return []

        self.db.add_all(metrics)
        self.db.commit()
        for metric in metrics:
            self.db.refresh(metric)
        return metrics

    def list_recent_metrics(
        self,
        limit: int = 100,
        device_id: int | None = None,
        metric_name: str | None = None,
        status: str | None = None,
    ) -> list[Metric]:
        query: Select[tuple[Metric]] = select(Metric)
        if device_id is not None:
            query = query.where(Metric.device_id == device_id)
        if metric_name:
            query = query.where(Metric.metric_name == metric_name)
        if status:
            query = query.where(Metric.status == status)
        query = query.order_by(desc(Metric.checked_at), desc(Metric.id)).limit(limit)
        return list(self.db.scalars(query).all())

    def list_latest_metrics(self) -> list[Metric]:
        metrics = self.list_recent_metrics(limit=1000)
        latest_by_key: dict[tuple[int, str], Metric] = {}
        for metric in metrics:
            key = (metric.device_id, metric.metric_name)
            if key not in latest_by_key:
                latest_by_key[key] = metric
        return list(latest_by_key.values())

    def latest_metric_map(self) -> dict[tuple[int, str], Metric]:
        return {(metric.device_id, metric.metric_name): metric for metric in self.list_latest_metrics()}

    def list_metric_names(self, device_id: int | None = None) -> list[str]:
        query = select(distinct(Metric.metric_name)).order_by(Metric.metric_name)
        if device_id is not None:
            query = query.where(Metric.device_id == device_id)
        return list(self.db.scalars(query).all())
