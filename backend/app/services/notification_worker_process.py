"""Signal lifecycle for a standalone notification worker process.

The caller owns transport, database engine, and asyncio.run(). This adapter must
run on the main thread of a dedicated process, not inside an API server that
already owns signal handling.
"""

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
import signal
from threading import current_thread, main_thread
from types import FrameType

from .notification_worker import NotificationWorkerReport


@contextmanager
def _shutdown_signals(stop: asyncio.Event) -> Iterator[None]:
    if current_thread() is not main_thread():
        raise RuntimeError("Notification process signal handling requires the main thread")
    loop = asyncio.get_running_loop()
    previous: dict[signal.Signals, int | Callable[[int, FrameType | None], object]] = {}

    def request_stop(_number: int, _frame: FrameType | None) -> None:
        # Repeated signals remain idempotent; the runner owns its grace deadline.
        loop.call_soon_threadsafe(stop.set)

    try:
        for number in (signal.SIGTERM, signal.SIGINT):
            handler = signal.getsignal(number)
            if handler is None:
                raise RuntimeError("Cannot safely restore the existing notification process signal handler")
            signal.signal(number, request_stop)
            previous[number] = handler
        yield
    finally:
        for number, handler in reversed(list(previous.items())):
            signal.signal(number, handler)


async def run_notification_process(
    worker: Callable[[asyncio.Event], Awaitable[NotificationWorkerReport]],
) -> NotificationWorkerReport:
    """Convert termination signals to the runner's graceful stop contract.

    Exceptions/cancellation propagate after restoring handlers. Resource disposal
    belongs in the caller's finally block; this adapter never creates an engine or
    opens a provider connection. SIGKILL cannot run cleanup and relies on leases.
    """
    stop = asyncio.Event()
    with _shutdown_signals(stop):
        return await worker(stop)
