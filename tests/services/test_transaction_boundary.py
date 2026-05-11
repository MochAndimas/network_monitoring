"""Define test module behavior for `tests/services/test_transaction_boundary.py`.

This module contains automated regression and validation scenarios.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.models.metric import Metric
from backend.app.models.scheduler_job_status import SchedulerJobStatus
from backend.app.models.threshold import Threshold
from backend.app.models.device import Device
from backend.app.models.user import AuthSession, User
from backend.app.core.security import hash_password, verify_password
from backend.app.repositories.device_repository import DeviceRepository
from backend.app.services import run_cycle_service
from backend.app.services.pipeline_control import monitoring_pipeline_guard
from backend.app.services.auth.admin import reset_user_password_for_admin
from backend.app.scheduler import jobs as scheduler_jobs
from backend.app.core.time import utcnow
from tests.test_utils import create_all, drop_all, run


def test_run_monitoring_cycle_rolls_back_metrics_when_alerting_fails(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    run(create_all(engine))

    async def fake_collect_monitoring_metrics():
        return [
            {
                "device_id": 1,
                "metric_name": "ping",
                "metric_value": "12.34",
                "status": "up",
                "unit": "ms",
                "checked_at": utcnow(),
            }
        ]

    async def fake_evaluate_alerts(_db, *, commit: bool = True):
        raise RuntimeError("forced-alerting-failure")

    monkeypatch.setattr(run_cycle_service, "collect_monitoring_metrics", fake_collect_monitoring_metrics)
    monkeypatch.setattr(run_cycle_service, "evaluate_alerts", fake_evaluate_alerts)

    async def scenario():
        async with session_factory() as db:
            await DeviceRepository(db).upsert_devices(
                [{"name": "Gateway", "ip_address": "192.168.1.1", "device_type": "internet_target"}]
            )
            with pytest.raises(RuntimeError, match="forced-alerting-failure"):
                await run_cycle_service.run_monitoring_cycle(db)

            metric_count = int(await db.scalar(select(func.count()).select_from(Metric)) or 0)
            return metric_count

    try:
        metric_count = run(scenario())
        assert metric_count == 0
    finally:
        run(drop_all(engine))


def test_device_upsert_can_join_outer_transaction_and_roll_back():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    run(create_all(engine))

    async def scenario():
        async with session_factory() as db:
            with pytest.raises(RuntimeError, match="forced-device-upsert-failure"):
                async with db.begin():
                    devices = await DeviceRepository(db).upsert_devices(
                        [
                            {
                                "name": "Gateway",
                                "ip_address": "192.168.1.1",
                                "device_type": "internet_target",
                            },
                            {
                                "name": "Core Router",
                                "ip_address": "192.168.1.254",
                                "device_type": "mikrotik",
                            },
                        ],
                        commit=False,
                    )
                    assert all(device.id is not None for device in devices)
                    raise RuntimeError("forced-device-upsert-failure")

        async with session_factory() as db:
            return int(await db.scalar(select(func.count()).select_from(Device)) or 0)

    try:
        device_count = run(scenario())
        assert device_count == 0
    finally:
        run(drop_all(engine))


def test_device_upsert_still_commits_by_default_for_existing_callers():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    run(create_all(engine))

    async def scenario():
        async with session_factory() as db:
            await DeviceRepository(db).upsert_devices(
                [
                    {
                        "name": "Gateway",
                        "ip_address": "192.168.1.1",
                        "device_type": "internet_target",
                    }
                ]
            )

        async with session_factory() as db:
            return int(await db.scalar(select(func.count()).select_from(Device)) or 0)

    try:
        device_count = run(scenario())
        assert device_count == 1
    finally:
        run(drop_all(engine))


def test_auth_password_reset_can_join_outer_transaction_and_roll_back():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    run(create_all(engine))

    async def scenario():
        async with session_factory.begin() as db:
            user = User(
                username="operator",
                full_name="Network Operator",
                password_hash=hash_password("OldStrongPass123!"),
                role="admin",
                is_active=True,
                password_changed_at=utcnow(),
            )
            db.add(user)
            await db.flush()
            db.add(
                AuthSession(
                    user_id=user.id,
                    jwt_id="session-to-keep-rollback-visible",
                    token_hash="session-token-hash",
                    expires_at=utcnow(),
                    last_seen_at=utcnow(),
                )
            )

        async with session_factory() as db:
            with pytest.raises(RuntimeError, match="forced-password-reset-failure"):
                async with db.begin():
                    await reset_user_password_for_admin(
                        db,
                        user_id=1,
                        new_password="NewStrongPass123!",
                        commit=False,
                    )
                    raise RuntimeError("forced-password-reset-failure")

        async with session_factory() as db:
            user = await db.get(User, 1)
            session = await db.scalar(
                select(AuthSession).where(AuthSession.jwt_id == "session-to-keep-rollback-visible")
            )
            return user, session

    try:
        user, session = run(scenario())
        assert user is not None
        assert verify_password("OldStrongPass123!", user.password_hash)
        assert session is not None
        assert session.revoked_at is None
    finally:
        run(drop_all(engine))


def test_monitoring_pipeline_guard_allows_independent_scopes():
    async def scenario():
        async with monitoring_pipeline_guard(wait=False, scope="metrics:internet") as first_acquired:
            assert first_acquired is True
            async with monitoring_pipeline_guard(wait=False, scope="metrics:internet") as same_scope_acquired:
                assert same_scope_acquired is False
            async with monitoring_pipeline_guard(wait=False, scope="metrics:server") as other_scope_acquired:
                assert other_scope_acquired is True

    run(scenario())


def test_scheduler_job_failure_rolls_back_domain_writes_and_updates_job_status(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False,
        },
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    run(create_all(engine))
    monkeypatch.setattr(scheduler_jobs, "SessionLocal", session_factory)

    async def failing_operation(db):
        db.add(
            Threshold(
                key="phase2_atomic_threshold",
                value=1.0,
                description="must rollback on failure",
            )
        )
        await db.flush()
        raise RuntimeError("forced-job-failure")

    async def scenario():
        with pytest.raises(RuntimeError, match="forced-job-failure"):
            await scheduler_jobs._run_scheduler_job("phase2_atomic_job", failing_operation)

        async with session_factory() as db:
            threshold = await db.scalar(
                select(Threshold).where(Threshold.key == "phase2_atomic_threshold")
            )
            job_status = await db.scalar(
                select(SchedulerJobStatus).where(SchedulerJobStatus.job_name == "phase2_atomic_job")
            )
            return threshold, job_status

    try:
        threshold, job_status = run(scenario())
        assert threshold is None
        assert job_status is not None
        assert job_status.is_running is False
        assert job_status.consecutive_failures == 1
        assert job_status.last_failed_at is not None
        assert "forced-job-failure" in str(job_status.last_error or "")
    finally:
        run(drop_all(engine))
