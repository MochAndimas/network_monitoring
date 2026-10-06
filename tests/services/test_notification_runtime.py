"""Operational queue lifecycle: multipart, restart-safe cursors and manual recovery."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

from sqlalchemy import select, update

from backend.app.core.time import utcnow
from backend.app.models.alert import Alert
from backend.app.models.notification_outbox import NotificationOutbox as Job
from backend.app.models.notification_worker import NotificationWorker
from backend.app.services.alert_notification_outbox_service import deliver_alert_notification
from backend.app.services.notification_delivery_service import DeliveryPolicy
from backend.app.services.notification_maintenance import redrive_notification, retain_notifications
from backend.app.services.notification_runtime import run_notification_runtime
from backend.app.services.notification_worker import NotificationWorkerPolicy
from backend.app.services.telegram_message_parts import telegram_message_parts
from backend.app.services.telegram_outbox_writer import TelegramOutboxWriter
from tests.services.test_telegram_outbox_writer import events
from tests.test_utils import run


def test_multipart_retries_resume_without_premature_domain_ack(outbox_sessions):
    async def scenario():
        now = utcnow()
        async with outbox_sessions.begin() as db:
            batch = (await events(db))[:1]
            batch[0]["message"] = "😀" * 5000
            await TelegramOutboxWriter("123")(db, batch)
            alert_id = batch[0]["alert_id"]
        sender = AsyncMock(side_effect=[True, False])
        policy = DeliveryPolicy(max_attempts=1)
        assert (
            await deliver_alert_notification(outbox_sessions, AsyncMock(), routed_sender=sender, policy=policy)
            == "dead"
        )
        async with outbox_sessions.begin() as db:
            job = await db.scalar(select(Job))
            assert job is not None and job.next_part == 1
            assert (await db.get(Alert, alert_id)).telegram_notified_at is None
            assert await redrive_notification(db, job.id, now=now)
            message = job.message
        resumed = AsyncMock(return_value=True)
        assert await deliver_alert_notification(outbox_sessions, AsyncMock(), routed_sender=resumed) == "sent"
        assert [call.args[1] for call in resumed.call_args_list] == list(telegram_message_parts(message)[1:])
        assert all(len(call.args[1].encode("utf-16-le")) // 2 <= 4096 for call in resumed.call_args_list)
        async with outbox_sessions.begin() as db:
            assert (await db.get(Alert, alert_id)).telegram_notified_at is not None
            assert not await redrive_notification(db, job.id, now=now)
            assert await retain_notifications(db, now=now + timedelta(days=40)) == 0
            await db.execute(update(Alert).values(status="resolved", resolved_at=now))
            assert await retain_notifications(db, now=now + timedelta(days=40)) == 1

    run(scenario())


def test_runtime_persists_heartbeat_and_finishes_inflight_send(outbox_sessions):
    async def scenario():
        async with outbox_sessions.begin() as db:
            await TelegramOutboxWriter("123")(db, await events(db))
        stop = asyncio.Event()

        async def sender(destination, message):
            async with outbox_sessions() as db:
                row = await db.get(NotificationWorker, "fixture")
                assert row is not None and row.status == "running"
            stop.set()
            return True

        report = await run_notification_runtime(
            outbox_sessions,
            sender,
            stop,
            worker_id="fixture",
            heartbeat_seconds=0.05,
            worker_policy=NotificationWorkerPolicy(concurrency=1, poll_seconds=0.01),
        )
        assert report.sent == 1
        async with outbox_sessions() as db:
            assert (await db.get(NotificationWorker, "fixture")).status == "stopped"
            assert (await db.scalar(select(Job.status))) == "sent"

    run(scenario())


def test_process_kill_and_restart_recovers_committed_multipart(outbox_sessions):
    import os
    import sys
    import textwrap

    child = textwrap.dedent("""
        import asyncio, sys
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from backend.app.services.notification_runtime import run_notification_runtime
        from backend.app.services.notification_worker_process import run_notification_process
        from backend.app.services.notification_worker import NotificationWorkerPolicy
        from backend.app.services.notification_delivery_service import DeliveryPolicy

        async def main():
            engine = create_async_engine(sys.argv[1])
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            calls = 0
            async def worker(stop):
                async def send(destination, message):
                    nonlocal calls
                    calls += 1
                    if sys.argv[2] == "crash" and calls == 2:
                        print("inflight", flush=True)
                        await asyncio.Event().wait()
                    if sys.argv[2] == "recover":
                        stop.set()
                    return True
                return await run_notification_runtime(sessions, send, stop,
                    worker_id=sys.argv[2], heartbeat_seconds=.1,
                    worker_policy=NotificationWorkerPolicy(concurrency=1, poll_seconds=.01),
                    delivery_policy=DeliveryPolicy(lease_seconds=2, send_timeout_seconds=1))
            try:
                report = await run_notification_process(worker)
                assert report.sent == 1
                print("recovered", flush=True)
            finally:
                await engine.dispose()
        asyncio.run(main())
    """)

    async def scenario():
        async with outbox_sessions.begin() as db:
            batch = (await events(db))[:1]
            batch[0]["message"] = "x" * 8500
            await TelegramOutboxWriter("123")(db, batch)
            database_url = str(db.bind.url)
        env = {**os.environ, "APP_ENV_FILE": ""}
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            child,
            database_url,
            "crash",
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            assert process.stdout is not None
            assert await asyncio.wait_for(process.stdout.readline(), 15) == b"inflight\n"
        finally:
            process.kill()
            await process.wait()
        async with outbox_sessions() as db:
            job = await db.scalar(select(Job))
            assert job.status == "processing" and job.next_part == 1
        await asyncio.sleep(2.1)
        recovered = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            child,
            database_url,
            "recover",
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(recovered.communicate(), 15)
        assert recovered.returncode == 0, stderr.decode()
        assert stdout == b"recovered\n"
        async with outbox_sessions() as db:
            job = await db.scalar(select(Job))
            assert job.status == "sent" and job.attempts == 2 and job.next_part == 3

    run(scenario())


def test_single_event_over_reference_batch_limit_acks_every_alert(outbox_sessions):
    async def scenario():
        async with outbox_sessions.begin() as db:
            batch = (await events(db))[:1]
            members = [batch[0]["alert"]]
            for _ in range(300):
                member = Alert(
                    device_id=members[0].device_id,
                    alert_type="device_down",
                    severity="critical",
                    message="fixture",
                    status="active",
                    created_at=utcnow(),
                )
                db.add(member)
                members.append(member)
            await db.flush()
            batch[0]["alerts"] = members
            await TelegramOutboxWriter("123")(db, batch)
            ids = [member.id for member in members]
        assert (
            await deliver_alert_notification(outbox_sessions, AsyncMock(), routed_sender=AsyncMock(return_value=True))
            == "sent"
        )
        async with outbox_sessions() as db:
            assert all((await db.scalars(select(Alert.telegram_notified_at).where(Alert.id.in_(ids)))).all())

    run(scenario())
