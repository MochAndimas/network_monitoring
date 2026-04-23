"""Provide operator and maintenance scripts for the network monitoring project."""

from __future__ import annotations

import argparse
import asyncio
import sys
import statistics
import time

import httpx


DEFAULT_PATHS = [
    "/health",
    "/dashboard/summary",
    "/dashboard/overview-panels",
    "/dashboard/overview-data",
    "/devices/paged?limit=100&offset=0",
    "/alerts/active",
    "/incidents?status=active",
    "/metrics/history/paged?limit=100&offset=0",
    "/metrics/history/context?limit=100&snapshot_limit=10&snapshot_offset=0",
    "/observability/summary",
]


async def _measure_path(client: httpx.AsyncClient, path: str, runs: int) -> dict:
    samples_ms: list[float] = []
    for _ in range(runs):
        started_at = time.perf_counter()
        response = await client.get(path)
        response.raise_for_status()
        samples_ms.append((time.perf_counter() - started_at) * 1000)

    return {
        "path": path,
        "runs": runs,
        "min_ms": min(samples_ms),
        "avg_ms": statistics.fmean(samples_ms),
        "p95_ms": sorted(samples_ms)[max(int(runs * 0.95) - 1, 0)],
        "max_ms": max(samples_ms),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark a set of backend endpoints.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Base backend URL.")
    parser.add_argument("--runs", type=int, default=5, help="Number of runs per endpoint.")
    parser.add_argument("--path", action="append", dest="paths", help="Endpoint path to benchmark. Can be repeated.")
    parser.add_argument("--api-key", default="", help="Optional x-api-key header.")
    parser.add_argument("--max-p95-ms", type=float, default=0.0, help="Optional p95 threshold. Zero disables the gate.")
    parser.add_argument("--max-max-ms", type=float, default=0.0, help="Optional max threshold. Zero disables the gate.")
    args = parser.parse_args()

    paths = args.paths or DEFAULT_PATHS
    headers = {"x-api-key": args.api_key} if args.api_key else {}

    async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), headers=headers, timeout=30.0) as client:
        results = await asyncio.gather(*[_measure_path(client, path, args.runs) for path in paths])

    print(f"Benchmark base URL: {args.base_url}")
    threshold_failures: list[str] = []
    for result in results:
        print(
            f"{result['path']:<32} "
            f"runs={result['runs']:<2} "
            f"min={result['min_ms']:.2f}ms "
            f"avg={result['avg_ms']:.2f}ms "
            f"p95={result['p95_ms']:.2f}ms "
            f"max={result['max_ms']:.2f}ms"
        )
        if args.max_p95_ms > 0 and result["p95_ms"] > args.max_p95_ms:
            threshold_failures.append(
                f"{result['path']} exceeded p95 threshold: {result['p95_ms']:.2f}ms > {args.max_p95_ms:.2f}ms"
            )
        if args.max_max_ms > 0 and result["max_ms"] > args.max_max_ms:
            threshold_failures.append(
                f"{result['path']} exceeded max threshold: {result['max_ms']:.2f}ms > {args.max_max_ms:.2f}ms"
            )

    if threshold_failures:
        print("\nBenchmark threshold failures:", file=sys.stderr)
        for failure in threshold_failures:
            print(f"- {failure}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
