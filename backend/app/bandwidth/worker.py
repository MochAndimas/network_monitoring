"""CLI for the optional IPFIX ingestion worker and its database heartbeat."""

import argparse
import asyncio
import logging
import signal
from pathlib import Path
from time import time_ns

from sqlalchemy import select

from ..core.config import configure_logging, settings
from ..db.session import SessionLocal, engine
from ..models.bandwidth_ingestion import BandwidthFlowStream
from .health import observation_is_fresh
from .ingestion_config import load_policy
from .ingestion_runtime import ingest_once, run_worker
from .spool import source_manifest, spool_lock


async def run(command: str) -> None:
    try:
        if not settings.bandwidth_ingestion_enabled or not settings.bandwidth_flow_policy_file:
            raise ValueError("Flow ingestion requires explicit enablement and policy file")
        directory = Path(settings.bandwidth_spool_directory)
        policy = load_policy(Path(settings.bandwidth_flow_policy_file))
        if command == "health":
            source = source_manifest(directory)
            if source.router_id != policy.flow.router_id:
                raise SystemExit(1)
            async with SessionLocal() as db:
                stream = await db.scalar(
                    select(BandwidthFlowStream).where(
                        BandwidthFlowStream.stream_id == source.stream_id,
                        BandwidthFlowStream.router_id == policy.flow.router_id,
                        BandwidthFlowStream.policy_digest == policy.digest,
                        BandwidthFlowStream.status.in_(("running", "idle")),
                    )
                )
            if stream is None or not observation_is_fresh(stream.heartbeat_ns, time_ns()):
                raise SystemExit(1)
        elif command == "once":
            with spool_lock(directory, "worker"):
                await ingest_once(
                    SessionLocal,
                    directory,
                    source_manifest(directory),
                    policy,
                    batch_size=settings.bandwidth_ingestion_batch_size,
                )
        else:
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            for number in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(number, stop.set)
            await run_worker(
                SessionLocal,
                directory,
                policy,
                stop,
                batch_size=settings.bandwidth_ingestion_batch_size,
                poll_seconds=settings.bandwidth_ingestion_poll_seconds,
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "once", "health"), default="run", nargs="?")
    args = parser.parse_args()
    configure_logging()
    try:
        asyncio.run(run(args.command))
    except Exception:
        logging.getLogger(__name__).error("Flow worker stopped; check policy, schema, database and spool health")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
