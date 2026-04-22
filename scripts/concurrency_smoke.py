"""Provide operator and maintenance scripts for the network monitoring project."""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time

import httpx


async def _hit_endpoint(client: httpx.AsyncClient, path: str, semaphore: asyncio.Semaphore) -> tuple[int, float]:
    """Handle the internal hit endpoint helper logic for operator and maintenance scripts. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        client: client value used by this routine (type `httpx.AsyncClient`).
        path: path value used by this routine (type `str`).
        semaphore: semaphore value used by this routine (type `asyncio.Semaphore`).

    Returns:
        `tuple[int, float]` result produced by the routine.
    """
    async with semaphore:
        started_at = time.perf_counter()
        response = await client.get(path)
        duration_ms = (time.perf_counter() - started_at) * 1000
        return response.status_code, duration_ms


async def main() -> None:
    """Handle main for operator and maintenance scripts. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Returns:
        None. The routine is executed for its side effects.
    """
    parser = argparse.ArgumentParser(description="Run a simple concurrency smoke test against one endpoint.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Base backend URL.")
    parser.add_argument("--path", default="/health/live", help="Endpoint path to exercise.")
    parser.add_argument("--requests", type=int, default=20, help="Total number of requests.")
    parser.add_argument("--concurrency", type=int, default=5, help="Maximum number of concurrent requests.")
    parser.add_argument("--api-key", default="", help="Optional x-api-key header.")
    parser.add_argument("--max-p95-ms", type=float, default=1000.0, help="P95 latency threshold.")
    args = parser.parse_args()

    headers = {"x-api-key": args.api_key} if args.api_key else {}
    semaphore = asyncio.Semaphore(max(args.concurrency, 1))

    async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), headers=headers, timeout=30.0) as client:
        results = await asyncio.gather(
            *[_hit_endpoint(client, args.path, semaphore) for _ in range(max(args.requests, 1))]
        )

    statuses = [status for status, _duration_ms in results]
    durations_ms = [duration_ms for _status, duration_ms in results]
    p95_ms = sorted(durations_ms)[max(int(len(durations_ms) * 0.95) - 1, 0)]
    failures = [status for status in statuses if status >= 400]

    print(
        f"Concurrency smoke path={args.path} requests={len(results)} concurrency={args.concurrency} "
        f"avg={statistics.fmean(durations_ms):.2f}ms p95={p95_ms:.2f}ms max={max(durations_ms):.2f}ms failures={len(failures)}"
    )

    if failures:
        print(f"Non-success statuses observed: {failures}", file=sys.stderr)
        raise SystemExit(1)
    if p95_ms > args.max_p95_ms:
        print(
            f"P95 latency threshold exceeded for {args.path}: {p95_ms:.2f}ms > {args.max_p95_ms:.2f}ms",
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
