"""Bounded index seeks for sample-based alert history.

Each branch limits IDs before the UNION and ORM fetch. Unlike window ranking,
the existing device/name/time/id index can stop after the requested samples,
including when those samples span a long collection outage.
"""

from collections.abc import Sequence

from sqlalchemy import Select, desc, select, union_all

from ...models.metric import Metric

MetricPair = tuple[int, str]
ALERT_HISTORY_PAIR_BATCH_SIZE = 64


def recent_metric_pairs_query(pairs: Sequence[MetricPair], *, per_pair_limit: int) -> Select[tuple[Metric]]:
    """Build one bounded batch; callers deduplicate pairs and split large inputs."""
    if not pairs or len(pairs) > ALERT_HISTORY_PAIR_BATCH_SIZE or per_pair_limit < 1:
        raise ValueError("Expected 1–64 metric pairs and a positive sample limit")
    branches = []
    for device_id, metric_name in pairs:
        newest_ids = (
            select(Metric.id)
            .where(Metric.device_id == device_id, Metric.metric_name == metric_name)
            .order_by(desc(Metric.checked_at), desc(Metric.id))
            .limit(per_pair_limit)
            .subquery()
        )
        branches.append(select(newest_ids.c.id))
    bounded_ids = union_all(*branches).subquery()
    return (
        select(Metric)
        .join(bounded_ids, Metric.id == bounded_ids.c.id)
        .order_by(Metric.device_id, Metric.metric_name, desc(Metric.checked_at), desc(Metric.id))
    )
