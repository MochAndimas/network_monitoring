"""Supervise GoFlow2 stdout directly into durable segments (never Docker logs)."""

import argparse
import asyncio
import logging
import os
import signal
from math import isfinite
from pathlib import Path
from time import monotonic, sleep

from .spool import SpoolError, SpoolWriter, source_manifest, spool_lock

logger = logging.getLogger(__name__)


async def collect_stdout(
    command: list[str],
    writer: SpoolWriter,
    stop: asyncio.Event,
    *,
    rotate_seconds: float = 5,
) -> None:
    """Bounded pipe buffering provides backpressure; UDP upstream can still drop.

    On graceful stop terminate the decoder, drain its stdout, then publish the
    final segment. Process death leaves .open files for next-start recovery.
    """
    if not isfinite(rotate_seconds) or rotate_seconds <= 0:
        raise ValueError("Rotation interval must be positive")
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        limit=writer.max_line_bytes,
    )
    assert process.stdout is not None
    read = asyncio.create_task(process.stdout.read(65536))
    stopping = asyncio.create_task(stop.wait())
    deadline = monotonic() + rotate_seconds
    drain_deadline: float | None = None
    partial = b""
    try:
        while True:
            if stop.is_set() and drain_deadline is None:
                if process.returncode is None:
                    process.terminate()
                drain_deadline = monotonic() + 5
            if drain_deadline is not None and monotonic() >= drain_deadline:
                raise SpoolError("collector_drain_timeout")
            tasks: set[asyncio.Task[bytes] | asyncio.Task[bool]] = {read}
            if drain_deadline is None:
                tasks.add(stopping)
            timeout = max(0, deadline - monotonic())
            done, _ = await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if read in done:
                chunk = read.result()
                if not chunk:
                    if partial.strip():
                        await asyncio.to_thread(writer.append, partial)
                    break
                buffered = partial + chunk
                split = buffered.rfind(b"\n") + 1
                complete, partial = buffered[:split], buffered[split:]
                if complete:
                    # GoFlow2's file transport may separate batches with blank
                    # lines. They are framing, not malformed flow records.
                    await asyncio.to_thread(
                        writer.append_many,
                        (line + b"\n" for line in complete.split(b"\n")[:-1] if line.strip()),
                    )
                if len(partial) > writer.max_line_bytes:
                    raise SpoolError("collector_line_too_large")
                read = asyncio.create_task(process.stdout.read(65536))
            if monotonic() >= deadline:
                await asyncio.to_thread(writer.seal)
                deadline = monotonic() + rotate_seconds
        code = await process.wait()
        if code != 0 and not stop.is_set():
            raise SpoolError("collector_process_failed")
    finally:
        read.cancel()
        stopping.cancel()
        await asyncio.gather(read, stopping, return_exceptions=True)
        if process.returncode is None:
            process.kill()
        await process.wait()
        await asyncio.to_thread(writer.seal)


async def run(args: argparse.Namespace) -> None:
    directory = Path(args.directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for number in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(number, stop.set)
    with spool_lock(directory, "writer"):
        source_manifest(directory, router_id=args.router_id)
        waiting = False

        def wait_for_capacity() -> bool:
            nonlocal waiting
            if not waiting:
                logger.warning("Flow spool full; waiting for consumer capacity without restarting decoder")
                waiting = True
            sleep(0.2)
            return not stop.is_set()

        writer = SpoolWriter(
            directory, segment_bytes=args.segment_bytes, max_bytes=args.max_bytes,
            wait_for_capacity=wait_for_capacity,
        )
        await asyncio.to_thread(writer.recover)
        await collect_stdout(
            [
                args.binary,
                "-listen",
                args.listen,
                "-mapping",
                args.mapping,
                "-format",
                "json",
                "-transport",
                "file",
            ],
            writer,
            stop,
            rotate_seconds=args.rotate_seconds,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default=os.environ.get("BANDWIDTH_SPOOL_DIRECTORY", "/var/lib/bandwidth-spool"))
    parser.add_argument("--router-id", type=int, required=True)
    parser.add_argument("--binary", default="/usr/local/bin/goflow2")
    parser.add_argument("--mapping", default="/etc/goflow2/mapping.yaml")
    # The pinned file transport writes payload and newline separately. Parallel
    # decoder workers can interleave them; keep this stdout pipeline serialized.
    parser.add_argument("--listen", default="netflow://:2055?count=1&workers=1")
    parser.add_argument("--segment-bytes", type=int, default=4 * 1024**2)
    parser.add_argument("--max-bytes", type=int, default=256 * 1024**2)
    parser.add_argument("--rotate-seconds", type=float, default=5)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except SpoolError as error:
        logger.error("Flow collector stopped: %s", error)
        raise SystemExit(1) from None
    except Exception:
        logger.error("Flow collector stopped; inspect process configuration, disk capacity and spool permissions")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
