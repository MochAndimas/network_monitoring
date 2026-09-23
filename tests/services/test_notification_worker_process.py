"""Real OS signals against disposable child processes; no provider or database."""

import os
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize("signal_name", ["SIGTERM", "SIGINT"])
@pytest.mark.parametrize("mode", ["idle", "drain", "deadline"])
def test_process_signal_drains_or_cancels_and_restores_handlers(signal_name, mode):
    source = textwrap.dedent("""
        import asyncio
        import os
        import signal
        import sys
        from backend.app.services.notification_worker import NotificationWorkerPolicy, run_notification_worker
        from backend.app.services.notification_worker_process import run_notification_process

        async def main():
            number = getattr(signal, sys.argv[1])
            mode = sys.argv[2]
            previous = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
            calls = cleaned = 0

            async def worker(stop):
                async def deliver():
                    nonlocal calls, cleaned
                    calls += 1
                    # Signal only after handlers and delivery are actually ready.
                    os.kill(os.getpid(), number)
                    if mode == "idle":
                        return "idle"
                    try:
                        await stop.wait()
                        os.kill(os.getpid(), number)
                        if mode == "deadline":
                            await asyncio.Event().wait()
                        return "sent"
                    finally:
                        cleaned += 1
                return await run_notification_worker(deliver, stop, policy=NotificationWorkerPolicy(
                    concurrency=1, poll_seconds=30, error_backoff_seconds=30, shutdown_grace_seconds=0.05
                ))

            report = await run_notification_process(worker)
            assert calls == 1
            assert all(signal.getsignal(s) == handler for s, handler in previous.items())
            assert report.cancelled_lanes == (1 if mode == "deadline" else 0)
            assert report.sent == (1 if mode == "drain" else 0)
            assert cleaned == (0 if mode == "idle" else 1)
            assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            print("signal lifecycle passed")

        asyncio.run(main())
    """)
    result = subprocess.run(
        [sys.executable, "-c", source, signal_name, mode],
        env={**os.environ, "APP_ENV_FILE": ""},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "signal lifecycle passed"


@pytest.mark.parametrize("cancelled", [False, True])
def test_process_failure_restores_signal_handlers(cancelled):
    import asyncio
    import signal
    from backend.app.services.notification_worker_process import run_notification_process

    async def scenario():
        previous = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT)}

        async def fail(_stop):
            if cancelled:
                raise asyncio.CancelledError()
            raise RuntimeError("fixture failure")

        with pytest.raises(asyncio.CancelledError if cancelled else RuntimeError):
            await run_notification_process(fail)
        assert all(signal.getsignal(number) == handler for number, handler in previous.items())

    asyncio.run(scenario())


def test_partial_signal_setup_restores_previous_handler(monkeypatch):
    import asyncio
    import signal
    from backend.app.services.notification_worker_process import run_notification_process

    original = signal.getsignal
    previous = original(signal.SIGTERM)
    monkeypatch.setattr(signal, "getsignal", lambda number: None if number == signal.SIGINT else original(number))

    async def scenario():
        async def never_started(_stop):
            pytest.fail("Worker must not start without restorable signal handlers")

        with pytest.raises(RuntimeError, match="Cannot safely restore"):
            await run_notification_process(never_started)
        assert original(signal.SIGTERM) == previous

    asyncio.run(scenario())
