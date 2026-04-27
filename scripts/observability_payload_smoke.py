"""Define module logic for `scripts/observability_payload_smoke.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import httpx


DEFAULT_WARMUP_PATHS = [
    "/devices/paged?limit=50&offset=0",
    "/alerts/active/paged?limit=50&offset=0",
    "/incidents/paged?status=active&limit=50&offset=0",
    "/metrics/history/paged?limit=50&offset=0",
    "/metrics/latest-snapshot/paged?limit=50&offset=0",
    "/metrics/daily-summary?limit=50&offset=0",
]

DEFAULT_EXPECT_ENDPOINTS = [
    "/devices/paged",
    "/alerts/active/paged",
    "/incidents/paged",
    "/metrics/history/paged",
    "/metrics/latest-snapshot/paged",
    "/metrics/daily-summary",
]

_METRIC_LINE_RE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\{([^}]*)\}\s+([-+]?[0-9]*\.?[0-9]+)\s*$')


def _parse_metric_lines(metrics_text: str, metric_name: str) -> list[tuple[dict[str, str], float]]:
    """Parse metric lines.

    Args:
        metrics_text: Parameter input untuk routine ini.
        metric_name: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    parsed: list[tuple[dict[str, str], float]] = []
    for line in str(metrics_text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _METRIC_LINE_RE.match(line)
        if not match:
            continue
        parsed_name, labels_raw, value_raw = match.groups()
        if parsed_name != metric_name:
            continue
        labels: dict[str, str] = {}
        for chunk in labels_raw.split(","):
            key, sep, value = chunk.partition("=")
            if not sep:
                continue
            labels[key.strip()] = value.strip().strip('"')
        parsed.append((labels, float(value_raw)))
    return parsed


def _find_missing_request_coverage(metrics_text: str, endpoints: list[str]) -> list[str]:
    """Perform find missing request coverage.

    Args:
        metrics_text: Parameter input untuk routine ini.
        endpoints: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    records = _parse_metric_lines(metrics_text, "network_monitoring_api_payload_requests_total")
    missing: list[str] = []
    for endpoint in endpoints:
        covered = any(labels.get("endpoint") == endpoint and value >= 1 for labels, value in records)
        if not covered:
            missing.append(endpoint)
    return missing


def _find_missing_rows_coverage(metrics_text: str, endpoints: list[str]) -> list[str]:
    """Perform find missing rows coverage.

    Args:
        metrics_text: Parameter input untuk routine ini.
        endpoints: Parameter input untuk routine ini.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    records = _parse_metric_lines(metrics_text, "network_monitoring_api_payload_rows_total")
    missing: list[str] = []
    for endpoint in endpoints:
        covered = any(labels.get("endpoint") == endpoint and labels.get("section") == "items" for labels, _value in records)
        if not covered:
            missing.append(endpoint)
    return missing


def _write_json(path: str | None, payload: dict) -> None:
    """Perform write json.

    Args:
        path: Parameter input untuk routine ini.
        payload: Parameter input untuk routine ini.

    """
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


async def main() -> None:
    """Run the module entrypoint.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    parser = argparse.ArgumentParser(description="Verify paged endpoint payload observability counters are emitted.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Base backend URL.")
    parser.add_argument("--api-key", default="", help="Optional x-api-key header.")
    parser.add_argument("--path", action="append", dest="paths", help="Warm-up endpoint path. Can be repeated.")
    parser.add_argument(
        "--expect-endpoint",
        action="append",
        dest="expected_endpoints",
        help="Endpoint label to require in payload counters. Can be repeated.",
    )
    parser.add_argument("--output-json", default="", help="Optional JSON artifact output path.")
    args = parser.parse_args()

    headers = {"x-api-key": args.api_key} if args.api_key else {}
    warmup_paths = args.paths or DEFAULT_WARMUP_PATHS
    expected_endpoints = args.expected_endpoints or DEFAULT_EXPECT_ENDPOINTS

    async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), headers=headers, timeout=30.0) as client:
        for path in warmup_paths:
            response = await client.get(path)
            response.raise_for_status()
        metrics_response = await client.get("/observability/metrics")
        metrics_response.raise_for_status()
        metrics_text = metrics_response.text

    missing_requests = _find_missing_request_coverage(metrics_text, expected_endpoints)
    missing_rows = _find_missing_rows_coverage(metrics_text, expected_endpoints)

    print(f"Observability payload smoke base URL: {args.base_url}")
    print(f"Warm-up paths: {len(warmup_paths)}")
    print(f"Expected endpoint labels: {len(expected_endpoints)}")
    _write_json(
        str(args.output_json or "").strip() or None,
        {
            "base_url": args.base_url,
            "warmup_paths": warmup_paths,
            "expected_endpoints": expected_endpoints,
            "missing_requests": missing_requests,
            "missing_rows": missing_rows,
            "ok": not missing_requests and not missing_rows,
        },
    )
    if not missing_requests and not missing_rows:
        print("All expected payload counters are present.")
        return

    print("\nObservability payload smoke failures:", file=sys.stderr)
    if missing_requests:
        print("- Missing request counters for endpoints:", file=sys.stderr)
        for endpoint in missing_requests:
            print(f"  - {endpoint}", file=sys.stderr)
    if missing_rows:
        print('- Missing rows counters (section="items") for endpoints:', file=sys.stderr)
        for endpoint in missing_rows:
            print(f"  - {endpoint}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
