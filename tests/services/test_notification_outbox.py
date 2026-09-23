"""Outbox transaction, retry, ordering, and crash-recovery contracts."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from backend.app.core.time import utcnow
from backend.app.models.notification_outbox import NotificationOutbox as Job
from backend.app.models.threshold import Threshold
from backend.app.repositories.notification_outbox_repository import (
    NotificationDraft,
    NotificationOutboxRepository as Repo,
)
from backend.app.services.notification_delivery_service import DeliveryPolicy, deliver_one
from tests.test_utils import run


def draft(key="active", stream="device:1"):
    return NotificationDraft(key, stream, "telegram", f"fixture {key}")


def test_enqueue_is_atomic_with_domain_state_and_idempotent(outbox_sessions):
    async def scenario():
        with pytest.raises(RuntimeError):
            async with outbox_sessions.begin() as db:
                db.add(Threshold(key="outbox-rollback", value=1))
                await db.flush()
                await Repo(db).enqueue(draft(), now=utcnow())
                raise RuntimeError("rollback domain and notification")
        async with outbox_sessions.begin() as db:
            assert await db.scalar(select(func.count()).select_from(Job)) == 0
            assert await db.scalar(select(func.count()).select_from(Threshold)) == 0
            first = await Repo(db).enqueue(draft(), now=utcnow())
            assert await Repo(db).enqueue(draft(), now=utcnow()) == first
            with pytest.raises(ValueError, match="different notification"):
                await Repo(db).enqueue(replace(draft(), message="different"), now=utcnow())
        async with outbox_sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Job)) == 1

    run(scenario())


def test_expired_lease_recovers_and_stale_ack_cannot_overwrite(outbox_sessions):
    async def scenario():
        now = utcnow()
        async with outbox_sessions.begin() as db:
            await Repo(db).enqueue(draft(), now=now)
        async with outbox_sessions.begin() as db:
            first = await Repo(db).claim_next(channel="telegram", now=now, lease_seconds=30, max_attempts=3)
            assert first
        async with outbox_sessions.begin() as db:
            assert (
                await Repo(db).claim_next(
                    channel="telegram", now=now + timedelta(seconds=29), lease_seconds=30, max_attempts=3
                )
                is None
            )
            second = await Repo(db).claim_next(
                channel="telegram", now=now + timedelta(seconds=31), lease_seconds=30, max_attempts=3
            )
            assert second and second.id == first.id and second.attempts == 2
            assert second.lease_token != first.lease_token
            assert not await Repo(db).acknowledge(
                first, now=now + timedelta(seconds=32), delivered=True, max_attempts=3, retry_seconds=0
            )
            assert await Repo(db).acknowledge(
                second, now=now + timedelta(seconds=32), delivered=True, max_attempts=3, retry_seconds=0
            )

    run(scenario())


def test_retry_blocks_following_stream_but_other_stream_can_proceed(outbox_sessions):
    async def scenario():
        now = utcnow()
        async with outbox_sessions.begin() as db:
            first_id = await Repo(db).enqueue(draft(), now=now)
            await Repo(db).enqueue(draft("resolved"), now=now)
            independent_id = await Repo(db).enqueue(draft("other", "device:2"), now=now)
        async with outbox_sessions.begin() as db:
            first = await Repo(db).claim_next(channel="telegram", now=now, lease_seconds=30, max_attempts=2)
            assert first and first.id == first_id
            assert await Repo(db).acknowledge(first, now=now, delivered=False, max_attempts=2, retry_seconds=5)
        async with outbox_sessions.begin() as db:
            other = await Repo(db).claim_next(channel="telegram", now=now, lease_seconds=30, max_attempts=2)
            assert other and other.id == independent_id
            await Repo(db).acknowledge(other, now=now, delivered=True, max_attempts=2, retry_seconds=0)
        async with outbox_sessions.begin() as db:
            assert (
                await Repo(db).claim_next(
                    channel="telegram", now=now + timedelta(seconds=4), lease_seconds=30, max_attempts=2
                )
                is None
            )
            retry = await Repo(db).claim_next(
                channel="telegram", now=now + timedelta(seconds=5), lease_seconds=30, max_attempts=2
            )
            assert retry and retry.id == first_id
            await Repo(db).acknowledge(
                retry, now=now + timedelta(seconds=5), delivered=False, max_attempts=2, retry_seconds=5
            )
        async with outbox_sessions.begin() as db:
            assert (
                await Repo(db).claim_next(
                    channel="telegram", now=now + timedelta(days=1), lease_seconds=30, max_attempts=2
                )
                is None
            )
            assert (await db.get(Job, first_id)).status == "dead"

    run(scenario())


def test_exhausted_crashed_worker_becomes_dead(outbox_sessions):
    async def scenario():
        now = utcnow()
        async with outbox_sessions.begin() as db:
            job_id = await Repo(db).enqueue(draft(), now=now)
        async with outbox_sessions.begin() as db:
            assert await Repo(db).claim_next(channel="telegram", now=now, lease_seconds=30, max_attempts=1)
        async with outbox_sessions.begin() as db:
            assert (
                await Repo(db).claim_next(
                    channel="telegram", now=now + timedelta(seconds=31), lease_seconds=30, max_attempts=1
                )
                is None
            )
            row = await db.get(Job, job_id)
            assert row.status == "dead" and row.last_error == "attempts_exhausted"

    run(scenario())


def test_delivery_releases_database_session_before_sender(outbox_sessions):
    async def scenario():
        now = utcnow()
        async with outbox_sessions.begin() as db:
            job_id = await Repo(db).enqueue(draft(), now=now)

        async def sender(message):
            assert message == draft().message
            # A separate connection can commit while network I/O is in progress.
            async with outbox_sessions.begin() as db:
                db.add(Threshold(key="during-network-send", value=1))
                row = await db.get(Job, job_id)
                assert row.status == "processing" and row.attempts == 1
            return True

        assert await deliver_one(outbox_sessions, sender, clock=lambda: now) == "sent"
        sender_again = AsyncMock(return_value=True)
        assert await deliver_one(outbox_sessions, sender_again, clock=lambda: now) == "idle"
        sender_again.assert_not_awaited()

    run(scenario())


def test_delivery_failure_retries_with_bounded_backoff(outbox_sessions):
    async def scenario():
        now = utcnow()
        async with outbox_sessions.begin() as db:
            await Repo(db).enqueue(draft(), now=now)
        sender = AsyncMock(side_effect=RuntimeError("provider secret must not be persisted"))
        policy = DeliveryPolicy(max_attempts=2)
        assert await deliver_one(outbox_sessions, sender, policy=policy, clock=lambda: now) == "retry"
        assert await deliver_one(outbox_sessions, sender, policy=policy, clock=lambda: now) == "idle"
        assert (
            await deliver_one(outbox_sessions, sender, policy=policy, clock=lambda: now + timedelta(seconds=5))
            == "dead"
        )
        async with outbox_sessions() as db:
            row = (await db.scalars(select(Job))).one()
            assert row.last_error == "delivery_failed"
        assert policy.retry_seconds(10000) == policy.retry_max_seconds

    run(scenario())


def test_uncommitted_job_is_not_delivered(outbox_sessions):
    async def scenario():
        now = utcnow()
        sender = AsyncMock(return_value=True)
        async with outbox_sessions.begin() as db:
            await Repo(db).enqueue(draft(), now=now)
            assert await deliver_one(outbox_sessions, sender, clock=lambda: now) == "idle"
            sender.assert_not_awaited()
        assert await deliver_one(outbox_sessions, sender, clock=lambda: now) == "sent"

    run(scenario())


def test_cancelled_delivery_can_be_reclaimed_after_lease(outbox_sessions):
    import asyncio

    async def scenario():
        now = utcnow()
        async with outbox_sessions.begin() as db:
            await Repo(db).enqueue(draft(), now=now)
        entered = asyncio.Event()

        async def sender(message):
            entered.set()
            await asyncio.Future()
            return True

        task = asyncio.create_task(deliver_one(outbox_sessions, sender, clock=lambda: now))
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        retry_sender = AsyncMock(return_value=True)
        assert await deliver_one(outbox_sessions, retry_sender, clock=lambda: now) == "idle"
        assert await deliver_one(outbox_sessions, retry_sender, clock=lambda: now + timedelta(seconds=61)) == "sent"

    run(scenario())


def test_crash_after_send_before_ack_can_duplicate_delivery(outbox_sessions, monkeypatch):
    async def scenario():
        now = utcnow()
        async with outbox_sessions.begin() as db:
            await Repo(db).enqueue(draft(), now=now)
        original_ack = Repo.acknowledge
        sender = AsyncMock(return_value=True)
        monkeypatch.setattr(Repo, "acknowledge", AsyncMock(side_effect=RuntimeError("ack unavailable")))
        with pytest.raises(RuntimeError, match="ack unavailable"):
            await deliver_one(outbox_sessions, sender, clock=lambda: now)
        monkeypatch.setattr(Repo, "acknowledge", original_ack)
        assert await deliver_one(outbox_sessions, sender, clock=lambda: now + timedelta(seconds=61)) == "sent"
        assert sender.await_count == 2  # at-least-once, not exactly-once external delivery

    run(scenario())


def test_delivery_timeout_is_retryable(outbox_sessions):
    import asyncio

    async def scenario():
        now = utcnow()
        async with outbox_sessions.begin() as db:
            await Repo(db).enqueue(draft(), now=now)

        async def sender(message):
            await asyncio.Future()
            return True

        assert (
            await deliver_one(
                outbox_sessions,
                sender,
                policy=DeliveryPolicy(send_timeout_seconds=1, lease_seconds=10),
                clock=lambda: now,
            )
            == "retry"
        )

    run(scenario())
