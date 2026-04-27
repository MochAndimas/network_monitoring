"""Define test module behavior for `tests/services/test_retention_service.py`.

This module contains automated regression and validation scenarios.
"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.models.alert import Alert
from backend.app.models.incident import Incident
from backend.app.models.metric import Metric
from backend.app.models.metric_cold_archive import MetricColdArchive
from backend.app.models.metric_daily_rollup import MetricDailyRollup
from backend.app.alerting.engine import evaluate_alerts
from backend.app.repositories.device_repository import DeviceRepository
from backend.app.repositories.metric_repository import MetricRepository
from backend.app.core.time import utcnow
from backend.app.services.retention_service import cleanup_monitoring_data
from tests.test_utils import create_all, drop_all, run

def test_cleanup_rolls_up_old_raw_metrics_and_prunes_resolved_records(monkeypatch):
    """Validate that cleanup rolls up old raw metrics and prunes resolved records.

    Args:
        monkeypatch: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = async_sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    run(create_all(engine))

    monkeypatch.setattr("backend.app.services.retention_service.settings.raw_metric_retention_days", 7)
    monkeypatch.setattr("backend.app.services.retention_service.settings.alert_retention_days", 180)
    monkeypatch.setattr("backend.app.services.retention_service.settings.incident_retention_days", 180)

    now = utcnow()
    old_timestamp = now - timedelta(days=9)
    recent_timestamp = now - timedelta(days=1)
    very_old_timestamp = now - timedelta(days=200)

    try:
        (
            result,
            rollup_by_date,
            old_rollup,
            cold_archives,
            remaining_metrics,
            remaining_alerts,
            remaining_incidents,
        ) = run(
            _cleanup_old_metrics(SessionLocal, old_timestamp, recent_timestamp, very_old_timestamp)
        )

        assert result["rolled_up_days"] == 2
        assert result["archived_metric_groups"] == 5
        assert result["deleted_metrics"] == 5
        assert result["deleted_alerts"] == 1
        assert result["deleted_incidents"] == 1
        assert set(rollup_by_date) == {old_timestamp.date(), recent_timestamp.date()}
        assert old_rollup.total_samples == 7
        assert old_rollup.ping_samples == 3
        assert old_rollup.down_count == 1
        assert round(old_rollup.uptime_percentage, 2) == 66.67
        assert old_rollup.average_ping_ms == 15.0
        assert old_rollup.min_ping_ms == 10.0
        assert old_rollup.max_ping_ms == 20.0
        assert round(old_rollup.average_packet_loss_percent, 2) == 16.66
        assert old_rollup.average_jitter_ms == 6.0
        assert old_rollup.max_jitter_ms == 8.0
        assert len(cold_archives) == 5
        ping_archive = next(
            archive for archive in cold_archives if archive.metric_name == "ping" and archive.status == "up"
        )
        assert ping_archive.archive_date == old_timestamp.date()
        assert ping_archive.sample_count == 2
        assert ping_archive.numeric_sample_count == 2
        assert ping_archive.last_metric_value == "20.00"
        assert ping_archive.avg_numeric_value == 15.0
        assert len(remaining_metrics) == 3
        assert {(metric.metric_name, metric.metric_value) for metric in remaining_metrics} == {
            ("jitter", "8.00"),
            ("packet_loss", "0.00"),
            ("ping", "5.00"),
        }
        assert [alert.status for alert in remaining_alerts] == ["active"]
        assert [incident.status for incident in remaining_incidents] == ["active"]
    finally:
        run(drop_all(engine))


def test_cleanup_rolls_up_yesterday_without_deleting_recent_raw_metrics(monkeypatch):
    """Validate that cleanup rolls up yesterday without deleting recent raw metrics.

    Args:
        monkeypatch: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = async_sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    run(create_all(engine))

    monkeypatch.setattr("backend.app.services.retention_service.settings.raw_metric_retention_days", 7)

    now = utcnow()
    yesterday = now - timedelta(days=1)

    try:
        result, rollups, remaining_metrics = run(_cleanup_yesterday_metrics(SessionLocal, yesterday))

        assert result["rolled_up_days"] == 1
        assert result["archived_metric_groups"] == 0
        assert result["deleted_metrics"] == 0
        assert len(rollups) == 1
        assert rollups[0].rollup_date == yesterday.date()
        assert len(remaining_metrics) == 2
    finally:
        run(drop_all(engine))


def test_latest_metric_map_uses_latest_metric_for_each_device_metric_pair():
    """Validate that latest metric map uses latest metric for each device metric pair.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = async_sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    run(create_all(engine))

    now = utcnow()

    try:
        device_id, latest_metrics = run(_latest_metric_map_for_device(SessionLocal, now))

        assert latest_metrics[(device_id, "ping")].metric_value == "timeout"
        assert latest_metrics[(device_id, "packet_loss")].metric_value == "0.00"
        assert len(latest_metrics) == 2
    finally:
        run(drop_all(engine))


def test_cleanup_keeps_latest_snapshot_metric_for_active_alert(monkeypatch):
    """Validate retention does not resolve active alerts without a recovery metric.

    Args:
        monkeypatch: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = async_sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    run(create_all(engine))

    monkeypatch.setattr("backend.app.services.retention_service.settings.raw_metric_retention_days", 7)
    monkeypatch.setattr("backend.app.alerting.engine.send_telegram_alert", _noop_send_telegram_alert)

    old_timestamp = utcnow() - timedelta(days=9)

    try:
        deleted_metrics, alert_statuses, latest_metric = run(
            _cleanup_with_active_down_alert(SessionLocal, old_timestamp)
        )

        assert deleted_metrics == 0
        assert alert_statuses == ["active"]
        assert latest_metric is not None
        assert latest_metric.status == "down"
        assert latest_metric.checked_at == old_timestamp
    finally:
        run(drop_all(engine))


def _metric(device_id: int, name: str, value: str, status: str, unit: str | None, checked_at):
    """Perform metric.

    Args:
        device_id: Parameter input untuk routine ini.
        name: Parameter input untuk routine ini.
        value: Parameter input untuk routine ini.
        status: Parameter input untuk routine ini.
        unit: Parameter input untuk routine ini.
        checked_at: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    return {
        "device_id": device_id,
        "metric_name": name,
        "metric_value": value,
        "status": status,
        "unit": unit,
        "checked_at": checked_at,
    }


async def _noop_send_telegram_alert(_message: str) -> None:
    """Perform noop send telegram alert.

    Args:
        _message: Parameter input untuk routine ini.

    """


async def _cleanup_old_metrics(session_factory, old_timestamp, recent_timestamp, very_old_timestamp):
    """Perform cleanup old metrics.

    Args:
        session_factory: Parameter input untuk routine ini.
        old_timestamp: Parameter input untuk routine ini.
        recent_timestamp: Parameter input untuk routine ini.
        very_old_timestamp: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    async with session_factory() as db:
        device = (
            await DeviceRepository(db).upsert_devices(
                [{"name": "AP Meeting Room", "ip_address": "192.168.1.40", "device_type": "access_point"}]
            )
        )[0]
        await MetricRepository(db).create_metrics(
            [
                _metric(device.id, "ping", "10.00", "up", "ms", old_timestamp),
                _metric(device.id, "ping", "20.00", "up", "ms", old_timestamp + timedelta(minutes=1)),
                _metric(device.id, "ping", "timeout", "down", None, old_timestamp + timedelta(minutes=2)),
                _metric(device.id, "packet_loss", "33.33", "warning", "%", old_timestamp),
                _metric(device.id, "packet_loss", "0.00", "up", "%", old_timestamp + timedelta(minutes=1)),
                _metric(device.id, "jitter", "4.00", "up", "ms", old_timestamp),
                _metric(device.id, "jitter", "8.00", "up", "ms", old_timestamp + timedelta(minutes=1)),
                _metric(device.id, "ping", "5.00", "up", "ms", recent_timestamp),
            ]
        )
        db.add_all(
            [
                Alert(
                    device_id=device.id,
                    alert_type="old_resolved",
                    severity="warning",
                    message="old resolved",
                    status="resolved",
                    created_at=very_old_timestamp,
                    resolved_at=very_old_timestamp,
                ),
                Alert(
                    device_id=device.id,
                    alert_type="old_active",
                    severity="critical",
                    message="old active",
                    status="active",
                    created_at=very_old_timestamp,
                ),
                Incident(
                    device_id=device.id,
                    status="resolved",
                    summary="old resolved",
                    started_at=very_old_timestamp,
                    ended_at=very_old_timestamp,
                ),
                Incident(
                    device_id=device.id,
                    status="active",
                    summary="old active",
                    started_at=very_old_timestamp,
                ),
            ]
        )
        await db.commit()

        result = await cleanup_monitoring_data(db)

        rollups = (await db.scalars(select(MetricDailyRollup))).all()
        rollup_by_date = {rollup.rollup_date: rollup for rollup in rollups}
        old_rollup = rollup_by_date[old_timestamp.date()]
        cold_archives = (await db.scalars(select(MetricColdArchive))).all()
        remaining_metrics = (await db.scalars(select(Metric))).all()
        remaining_alerts = (await db.scalars(select(Alert))).all()
        remaining_incidents = (await db.scalars(select(Incident))).all()
        return result, rollup_by_date, old_rollup, cold_archives, remaining_metrics, remaining_alerts, remaining_incidents


async def _cleanup_yesterday_metrics(session_factory, yesterday):
    """Perform cleanup yesterday metrics.

    Args:
        session_factory: Parameter input untuk routine ini.
        yesterday: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    async with session_factory() as db:
        device = (
            await DeviceRepository(db).upsert_devices(
                [{"name": "AP Meeting Room", "ip_address": "192.168.1.40", "device_type": "access_point"}]
            )
        )[0]
        await MetricRepository(db).create_metrics(
            [
                _metric(device.id, "ping", "10.00", "up", "ms", yesterday),
                _metric(device.id, "packet_loss", "0.00", "up", "%", yesterday),
            ]
        )

        result = await cleanup_monitoring_data(db)

        rollups = (await db.scalars(select(MetricDailyRollup))).all()
        remaining_metrics = (await db.scalars(select(Metric))).all()
        return result, rollups, remaining_metrics


async def _latest_metric_map_for_device(session_factory, now):
    """Perform latest metric map for device.

    Args:
        session_factory: Parameter input untuk routine ini.
        now: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    async with session_factory() as db:
        device = (
            await DeviceRepository(db).upsert_devices(
                [{"name": "Gateway", "ip_address": "192.168.1.1", "device_type": "internet_target"}]
            )
        )[0]
        device_id = device.id
        await MetricRepository(db).create_metrics(
            [
                _metric(device_id, "ping", "10.00", "up", "ms", now - timedelta(minutes=2)),
                _metric(device_id, "ping", "timeout", "down", None, now),
                _metric(device_id, "packet_loss", "0.00", "up", "%", now - timedelta(minutes=1)),
            ]
        )
        latest_metrics = await MetricRepository(db).latest_metric_map()
        return device_id, latest_metrics


async def _cleanup_with_active_down_alert(session_factory, old_timestamp):
    """Perform cleanup with active down alert.

    Args:
        session_factory: Parameter input untuk routine ini.
        old_timestamp: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    async with session_factory() as db:
        device = (
            await DeviceRepository(db).upsert_devices(
                [{"name": "AP Hallway", "ip_address": "192.168.1.41", "device_type": "access_point"}]
            )
        )[0]
        await MetricRepository(db).create_metrics(
            [_metric(device.id, "ping", "timeout", "down", None, old_timestamp)]
        )

        created_notifications = await evaluate_alerts(db)
        assert [notification["action"] for notification in created_notifications] == ["created"]

        result = await cleanup_monitoring_data(db)
        second_notifications = await evaluate_alerts(db)
        assert second_notifications == []

        alerts = list((await db.scalars(select(Alert).where(Alert.device_id == device.id))).all())
        latest_metrics = await MetricRepository(db).latest_metric_map()
        return (
            result["deleted_metrics"],
            [alert.status for alert in alerts],
            latest_metrics.get((device.id, "ping")),
        )
