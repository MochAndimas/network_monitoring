"""Exercise bounded concurrency, shutdown, error backoff, and lease recovery."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from backend.app.core.time import utcnow
from backend.app.models import Alert, Device, NotificationOutbox
from backend.app.repositories.notification_outbox_repository import NotificationDraft
from backend.app.services.alert_notification_outbox_service import (
    AlertNotificationReference,
    enqueue_alert_notification,
)
from backend.app.services.notification_worker import (
    NotificationWorkerPolicy,
    run_alert_notification_worker,
    run_notification_worker,
)
from tests.test_utils import run

POLICY = NotificationWorkerPolicy(
    concurrency=2, poll_seconds=0.01, error_backoff_seconds=0.02, shutdown_grace_seconds=0.2
)


def test_stop_drains_inflight_without_starting_another_delivery():
    async def scenario():
        stop, ready, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        active = calls = peak = 0

        async def deliver():
            nonlocal active, calls, peak
            active += 1
            calls += 1
            peak = max(peak, active)
            if active == 2:
                ready.set()
            try:
                await release.wait()
                return "sent"
            finally:
                active -= 1

        task = asyncio.create_task(run_notification_worker(deliver, stop, policy=POLICY))
        await asyncio.wait_for(ready.wait(), 1)
        stop.set()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        report = await asyncio.wait_for(task, 1)
        assert (peak, calls, active) == (2, 2, 0)
        assert report.sent == 2 and report.cancelled_lanes == 0

    run(scenario())


def test_grace_deadline_cancels_and_joins_every_lane():
    async def scenario():
        stop, ready = asyncio.Event(), asyncio.Event()
        entered = cleaned = 0

        async def deliver():
            nonlocal entered, cleaned
            entered += 1
            if entered == 2:
                ready.set()
            try:
                await asyncio.Event().wait()
                return "sent"
            finally:
                cleaned += 1

        task = asyncio.create_task(
            run_notification_worker(deliver, stop, policy=replace(POLICY, shutdown_grace_seconds=0.01))
        )
        await asyncio.wait_for(ready.wait(), 1)
        stop.set()
        report = await asyncio.wait_for(task, 1)
        assert report.cancelled_lanes == cleaned == 2

    run(scenario())


def test_errors_back_off_without_exposing_exception_text(caplog):
    async def scenario():
        stop = asyncio.Event()
        times = []

        async def deliver():
            times.append(asyncio.get_running_loop().time())
            if len(times) == 2:
                stop.set()
                return "idle"
            raise RuntimeError("secret-provider-token")

        report = await asyncio.wait_for(
            run_notification_worker(deliver, stop, policy=replace(POLICY, concurrency=1)), 1
        )
        assert report.errors == 1 and report.idle_polls == 1
        assert times[1] - times[0] >= POLICY.error_backoff_seconds

    run(scenario())
    assert "secret-provider-token" not in caplog.text
    assert "category=delivery_error" in caplog.text


def test_stop_wakes_idle_poll_without_waiting_for_interval():
    async def scenario():
        stop, called = asyncio.Event(), asyncio.Event()

        async def deliver():
            called.set()
            return "idle"

        task = asyncio.create_task(
            run_notification_worker(
                deliver, stop, policy=replace(POLICY, concurrency=1, poll_seconds=30, error_backoff_seconds=30)
            )
        )
        await asyncio.wait_for(called.wait(), 1)
        stop.set()
        report = await asyncio.wait_for(task, 1)
        assert report.idle_polls == 1

    run(scenario())


def test_pre_stopped_worker_does_not_touch_delivery():
    async def scenario():
        stop = asyncio.Event()
        stop.set()
        deliver = AsyncMock()
        report = await run_notification_worker(deliver, stop)
        deliver.assert_not_awaited()
        assert report.sent == report.errors == report.cancelled_lanes == 0

    run(scenario())


def test_unexpected_lane_cancellation_terminates_worker():
    async def scenario():
        async def deliver():
            raise asyncio.CancelledError()

        with pytest.raises(RuntimeError, match="lane stopped unexpectedly"):
            await asyncio.wait_for(run_notification_worker(deliver, asyncio.Event(), policy=POLICY), 1)

    run(scenario())


@pytest.mark.parametrize(
    "changes",
    [
        {"concurrency": 0},
        {"concurrency": 17},
        {"concurrency": True},
        {"poll_seconds": 0},
        {"poll_seconds": float("nan")},
        {"shutdown_grace_seconds": float("inf")},
        {"poll_seconds": 5, "error_backoff_seconds": 1},
    ],
)
def test_invalid_worker_configuration(changes):
    with pytest.raises(ValueError):
        replace(POLICY, **changes)


def test_cancelled_worker_restart_recovers_lease_and_acknowledges_domain(outbox_sessions):
    async def scenario():
        now = utcnow()
        async with outbox_sessions.begin() as db:
            device = Device(name="Worker fixture", ip_address="10.173.0.1", device_type="switch", site="fixture")
            db.add(device)
            await db.flush()
            alert = Alert(
                device_id=device.id,
                alert_type="device_down",
                severity="critical",
                message="fixture",
                status="active",
                created_at=now,
            )
            db.add(alert)
            await db.flush()
            alert_id = alert.id
            job_id = await enqueue_alert_notification(
                db,
                NotificationDraft("worker-restart", "fixture", "telegram", "fixture"),
                (AlertNotificationReference(alert_id, "active"),),
                now=now,
            )
        accepted = asyncio.Event()
        messages = []

        async def interrupted_sender(message):
            messages.append(message)
            accepted.set()
            await asyncio.Event().wait()
            return True

        first = asyncio.create_task(
            run_alert_notification_worker(
                outbox_sessions,
                interrupted_sender,
                asyncio.Event(),
                worker_policy=replace(POLICY, concurrency=1),
                clock=lambda: now,
            )
        )
        await asyncio.wait_for(accepted.wait(), 2)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        async with outbox_sessions() as db:
            job = await db.get(NotificationOutbox, job_id)
            assert job is not None and job.status == "processing" and job.attempts == 1
        stop = asyncio.Event()

        async def recovered_sender(message):
            messages.append(message)
            stop.set()
            return True

        report = await asyncio.wait_for(
            run_alert_notification_worker(
                outbox_sessions,
                recovered_sender,
                stop,
                worker_policy=replace(POLICY, concurrency=1),
                clock=lambda: now + timedelta(seconds=61),
            ),
            2,
        )
        assert report.sent == 1 and messages == ["fixture", "fixture"]  # At-least-once after interrupted delivery.
        async with outbox_sessions() as db:
            job = await db.get(NotificationOutbox, job_id)
            alert = await db.get(Alert, alert_id)
            assert job is not None and job.status == "sent" and job.attempts == 2
            assert alert is not None and alert.telegram_notified_at == now + timedelta(seconds=61)

    run(scenario())
