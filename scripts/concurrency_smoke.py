"""Provide operator and maintenance scripts for the network monitoring project."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import httpx


DEFAULT_PATHS = [
    "/health/live",
    "/devices/paged?limit=50&offset=0",
    "/alerts/active/paged?limit=50&offset=0",
    "/incidents/paged?status=active&limit=50&offset=0",
    "/metrics/history/paged?limit=50&offset=0",
]


async def _hit_endpoint(client: httpx.AsyncClient, path: str, semaphore: asyncio.Semaphore) -> tuple[int, float]:
    async with semaphore:
        started_at = time.perf_counter()
        response = await client.get(path)
        duration_ms = (time.perf_counter() - started_at) * 1000
        return response.status_code, duration_ms


async def _measure_path(
    client: httpx.AsyncClient,
    *,
    path: str,
    requests: int,
    semaphore: asyncio.Semaphore,
) -> dict:
    results = await asyncio.gather(*[_hit_endpoint(client, path, semaphore) for _ in range(max(requests, 1))])
    return _summarize_results(path=path, results=results)


def _summarize_results(*, path: str, results: list[tuple[int, float]]) -> dict:
    statuses = [status for status, _duration_ms in results]
    durations_ms = [duration_ms for _status, duration_ms in results]
    p95_ms = sorted(durations_ms)[max(int(len(durations_ms) * 0.95) - 1, 0)]
    return {
        "path": path,
        "requests": len(results),
        "avg_ms": statistics.fmean(durations_ms),
        "p95_ms": p95_ms,
        "max_ms": max(durations_ms),
        "failures": [status for status in statuses if status >= 400],
    }


def _collect_gate_failures(
    *,
    result: dict,
    max_p95_ms: float,
    max_max_ms: float,
) -> list[str]:
    failures: list[str] = []
    path = str(result.get("path") or "/unknown")
    status_failures = list(result.get("failures") or [])
    if status_failures:
        failures.append(f"{path} returned non-success statuses: {status_failures}")
    if max_p95_ms > 0 and float(result.get("p95_ms") or 0.0) > max_p95_ms:
        failures.append(f"{path} exceeded p95 threshold: {float(result['p95_ms']):.2f}ms > {max_p95_ms:.2f}ms")
    if max_max_ms > 0 and float(result.get("max_ms") or 0.0) > max_max_ms:
        failures.append(f"{path} exceeded max threshold: {float(result['max_ms']):.2f}ms > {max_max_ms:.2f}ms")
    return failures


def _resolve_thresholds(*, profile: str, max_p95_ms: float, max_max_ms: float) -> tuple[float, float]:
    if profile == "ci":
        return 1500.0, 2500.0
    if profile == "strict":
        return 1000.0, 2000.0
    return max_p95_ms, max_max_ms


def _print_latency_summary(results: list[dict]) -> None:
    if not results:
        return
    by_p95 = sorted(results, key=lambda item: float(item.get("p95_ms") or 0.0), reverse=True)[:3]
    print("Top concurrency latency (p95):")
    for item in by_p95:
        print(
            f"- {item['path']}: p95={item['p95_ms']:.2f}ms max={item['max_ms']:.2f}ms failures={len(item['failures'])}"
        )


def _write_json(path: str | None, payload: dict) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run concurrency smoke tests against one or more endpoints.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Base backend URL.")
    parser.add_argument("--path", action="append", dest="paths", help="Endpoint path to exercise. Can be repeated.")
    parser.add_argument("--requests", type=int, default=20, help="Total number of requests.")
    parser.add_argument("--concurrency", type=int, default=5, help="Maximum number of concurrent requests.")
    parser.add_argument("--api-key", default="", help="Optional x-api-key header.")
    parser.add_argument(
        "--profile",
        choices=["custom", "ci", "strict"],
        default="custom",
        help="Threshold profile. custom uses --max-p95-ms/--max-max-ms values.",
    )
    parser.add_argument("--max-p95-ms", type=float, default=1000.0, help="P95 latency threshold.")
    parser.add_argument("--max-max-ms", type=float, default=0.0, help="Max latency threshold. Zero disables the gate.")
    parser.add_argument("--output-json", default="", help="Optional JSON artifact output path.")
    args = parser.parse_args()

    paths = args.paths or DEFAULT_PATHS
    headers = {"x-api-key": args.api_key} if args.api_key else {}
    semaphore = asyncio.Semaphore(max(args.concurrency, 1))
    resolved_max_p95_ms, resolved_max_max_ms = _resolve_thresholds(
        profile=str(args.profile),
        max_p95_ms=float(args.max_p95_ms),
        max_max_ms=float(args.max_max_ms),
    )

    async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), headers=headers, timeout=30.0) as client:
        measured = [
            await _measure_path(
                client,
                path=path,
                requests=max(args.requests, 1),
                semaphore=semaphore,
            )
            for path in paths
        ]

    threshold_failures: list[str] = []
    for result in measured:
        print(
            f"Concurrency smoke path={result['path']} requests={result['requests']} concurrency={args.concurrency} "
            f"avg={result['avg_ms']:.2f}ms p95={result['p95_ms']:.2f}ms max={result['max_ms']:.2f}ms "
            f"failures={len(result['failures'])}"
        )
        threshold_failures.extend(
            _collect_gate_failures(
                result=result,
                max_p95_ms=resolved_max_p95_ms,
                max_max_ms=resolved_max_max_ms,
            )
        )

    print(
        f"Threshold profile={args.profile} max_p95_ms={resolved_max_p95_ms:.2f} max_max_ms={resolved_max_max_ms:.2f}"
    )
    _print_latency_summary(measured)
    _write_json(
        str(args.output_json or "").strip() or None,
        {
            "base_url": args.base_url,
            "profile": args.profile,
            "thresholds": {"max_p95_ms": resolved_max_p95_ms, "max_max_ms": resolved_max_max_ms},
            "paths": paths,
            "requests": max(args.requests, 1),
            "concurrency": max(args.concurrency, 1),
            "results": measured,
            "failures": threshold_failures,
        },
    )

    if threshold_failures:
        print("\nConcurrency smoke threshold failures:", file=sys.stderr)
        for failure in threshold_failures:
            print(f"- {failure}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
