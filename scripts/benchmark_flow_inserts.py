"""Synthetic insert/commit benchmark. Refuses nonempty or non-test databases."""

import argparse
import asyncio
import json
import random
from statistics import median
from time import perf_counter, time_ns
from uuid import uuid4

from sqlalchemy import func, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import backend.app.models  # noqa: F401 -- register the complete disposable schema
from backend.app.db.base import Base
from backend.app.models.device import Device
from backend.app.models.bandwidth_ingestion import BandwidthFlow, BandwidthFlowSegment, BandwidthFlowStream
from backend.app.services.bandwidth_ingestion_service import insert_flow_rows


def validate_url(value):
    url = make_url(value)
    if url.drivername != "mysql+aiomysql" or not (url.database or "").endswith("_test"):
        raise ValueError("Requires a dedicated mysql+aiomysql database ending in _test")
    return url


async def benchmark(url, rows=2000, rounds=3):
    engine = create_async_engine(validate_url(url), pool_size=1, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            existing = await connection.run_sync(lambda conn: inspect(conn).get_table_names())
            if existing:
                raise ValueError("Test database must be empty; existing tables will not be modified")
            await connection.run_sync(Base.metadata.create_all)
        stream = str(uuid4())
        async with sessions.begin() as db:
            db.add(Device(id=1, name="Synthetic benchmark router", ip_address="192.0.2.1", device_type="mikrotik"))
            await db.flush()
            db.add(BandwidthFlowStream(stream_id=stream, router_id=1, policy_digest="0" * 64,
                                       heartbeat_ns=time_ns(), status="idle"))
        samples = []
        rng = random.Random(20261104)
        for turn in range(-1, rounds):
            # Warm the driver/schema/cache path before timed comparisons.
            sizes = [0] if turn == -1 else [0, 50, 100, 250, 500, 1000]
            rng.shuffle(sizes)
            for size in sizes:
                segment = uuid4().hex
                async with sessions.begin() as db:
                    db.add(BandwidthFlowSegment(stream_id=stream, segment_id=segment, checksum="0" * 64,
                                               size_bytes=rows, offset_bytes=0, accepted_count=0,
                                               rejected_count=0, completed=False))
                now = time_ns()
                values = [dict(stream_id=stream, segment_id=segment, record_offset=i, router_id=1,
                               client_id=None, direction="upload", device_ip=f"192.168.1.{i % 200 + 1}",
                               remote_ip="198.51.100.1", source_ip=f"192.168.1.{i % 200 + 1}",
                               destination_ip="198.51.100.1", post_nat_source=None, post_nat_destination=None,
                               input_interface=13, output_interface=10, byte_count=4096, packets=4,
                               started_ns=now - 1000000, ended_ns=now, received_ns=now) for i in range(rows)]
                async with sessions() as db:
                    start = perf_counter()
                    calls = await insert_flow_rows(db, values, chunk_size=size)
                    inserted = perf_counter()
                    await db.commit()
                    committed = perf_counter()
                sample = dict(round=turn + 1, chunk_size=size, rows=rows, execute_calls=calls,
                              insert_ms=round((inserted-start)*1000, 3),
                              commit_ms=round((committed-inserted)*1000, 3),
                              total_ms=round((committed-start)*1000, 3))
                if turn == -1:
                    sample["warmup"] = True
                else:
                    samples.append(sample)
                print(json.dumps(sample), flush=True)
        async with sessions() as db:
            actual = await db.scalar(select(func.count()).select_from(BandwidthFlow))
        if actual != rows * (rounds * 6 + 1):
            raise ValueError("Benchmark row count mismatch")
        for size in [0, 50, 100, 250, 500, 1000]:
            group = [row for row in samples if row["chunk_size"] == size]
            print(json.dumps(dict(summary=True, chunk_size=size,
                                  median_insert_ms=median(row["insert_ms"] for row in group),
                                  median_commit_ms=median(row["commit_ms"] for row in group),
                                  median_total_ms=median(row["total_ms"] for row in group))), flush=True)
        print(json.dumps(dict(verified_rows=actual, note="Synthetic local test; not NAS storage performance")))
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, choices=range(1, 10001), default=2000)
    parser.add_argument("--rounds", type=int, choices=range(1, 11), default=3)
    args = parser.parse_args()
    import os
    try:
        asyncio.run(benchmark(os.environ["BANDWIDTH_BENCHMARK_DATABASE_URL"], args.rows, args.rounds))
    except Exception as error:
        # Never print connection URLs, SQL parameters or exception text.
        print(f"Benchmark failed: {type(error).__name__}; use a dedicated empty *_test database.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
