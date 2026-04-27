"""Define module logic for `scripts/nonfunctional_report.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass
class GateStatus:
    """Perform GateStatus.

    This class encapsulates related behavior and data for this domain area.
    """

    name: str
    passed: bool
    details: str


def _load_json(path: Path) -> dict[str, Any]:
    """Load json.

    Args:
        path: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _top_latency_rows(results: list[dict[str, Any]], metric_key: str) -> list[dict[str, Any]]:
    """Perform top latency rows.

    Args:
        results: Parameter input untuk routine ini.
        metric_key: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    return sorted(results, key=lambda item: float(item.get(metric_key) or 0.0), reverse=True)[:3]


def _ratio_percentage(passed_count: int, total_count: int) -> float:
    """Perform ratio percentage.

    Args:
        passed_count: Parameter input untuk routine ini.
        total_count: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    if total_count <= 0:
        return 0.0
    return (float(passed_count) / float(total_count)) * 100.0


def _week_range(reference_day: date) -> tuple[date, date]:
    """Perform week range.

    Args:
        reference_day: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    week_start = reference_day - timedelta(days=reference_day.weekday())
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def _render_gate_row(gate: GateStatus) -> str:
    """Render gate row.

    Args:
        gate: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    return f"| {gate.name} | {'PASS' if gate.passed else 'FAIL'} | {gate.details} |"


def _render_top_latency_lines(title: str, rows: list[dict[str, Any]], metric_key: str) -> list[str]:
    """Render top latency lines.

    Args:
        title: Parameter input untuk routine ini.
        rows: Parameter input untuk routine ini.
        metric_key: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    lines = [f"### {title}"]
    if not rows:
        lines.append("- data tidak tersedia")
        return lines
    for row in rows:
        path = str(row.get("path") or "/unknown")
        p95 = float(row.get("p95_ms") or 0.0)
        max_latency = float(row.get("max_ms") or 0.0)
        metric_value = float(row.get(metric_key) or 0.0)
        lines.append(f"- `{path}`: p95={p95:.2f}ms max={max_latency:.2f}ms metric={metric_value:.2f}")
    return lines


def _build_triage_markdown(
    *,
    benchmark_payload: dict[str, Any],
    concurrency_payload: dict[str, Any],
    observability_payload: dict[str, Any],
    generated_at: datetime,
) -> str:
    """Build triage markdown.

    Args:
        benchmark_payload: Parameter input untuk routine ini.
        concurrency_payload: Parameter input untuk routine ini.
        observability_payload: Parameter input untuk routine ini.
        generated_at: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    benchmark_failures = list(benchmark_payload.get("failures") or [])
    concurrency_failures = list(concurrency_payload.get("failures") or [])
    missing_requests = list(observability_payload.get("missing_requests") or [])
    missing_rows = list(observability_payload.get("missing_rows") or [])

    gates = [
        GateStatus(
            name="Benchmark regression",
            passed=bool(benchmark_payload) and not benchmark_failures,
            details=f"failures={len(benchmark_failures)}",
        ),
        GateStatus(
            name="Concurrency smoke",
            passed=bool(concurrency_payload) and not concurrency_failures,
            details=f"failures={len(concurrency_failures)}",
        ),
        GateStatus(
            name="Observability payload coverage",
            passed=bool(observability_payload) and not missing_requests and not missing_rows,
            details=f"missing_requests={len(missing_requests)}, missing_rows={len(missing_rows)}",
        ),
    ]

    benchmark_top_p95 = _top_latency_rows(list(benchmark_payload.get("results") or []), "p95_ms")
    concurrency_top_p95 = _top_latency_rows(list(concurrency_payload.get("results") or []), "p95_ms")

    lines = [
        "# Non-Functional Triage Summary",
        "",
        f"- Generated at (UTC): {generated_at.isoformat()}",
        "",
        "## Gate Status",
        "",
        "| Gate | Status | Detail |",
        "| --- | --- | --- |",
        *[_render_gate_row(gate) for gate in gates],
        "",
        "## Triage Checklist (Standar)",
        "",
        "1. Download artifact `non-functional-smoke-artifacts` untuk run ini.",
        "2. Cek `benchmark.json` dan `concurrency.json` untuk endpoint latency tertinggi.",
        "3. Cek `observability_payload.json` untuk `missing_requests` atau `missing_rows`.",
        "4. Cek `uvicorn.log` untuk stack trace/error saat smoke berjalan.",
        "5. Catat endpoint paling bermasalah, owner, dan action perbaikan sebelum merge.",
        "",
        *_render_top_latency_lines("Top Benchmark Latency (p95)", benchmark_top_p95, "p95_ms"),
        "",
        *_render_top_latency_lines("Top Concurrency Latency (p95)", concurrency_top_p95, "p95_ms"),
        "",
        "## Coverage Gaps",
        "",
        f"- missing request counters: {missing_requests if missing_requests else 'none'}",
        f"- missing rows counters: {missing_rows if missing_rows else 'none'}",
        "",
    ]
    return "\n".join(lines).strip() + "\n"


def _build_sla_summary(
    *,
    benchmark_payload: dict[str, Any],
    concurrency_payload: dict[str, Any],
    observability_payload: dict[str, Any],
    generated_day: date,
) -> dict[str, Any]:
    """Build sla summary.

    Args:
        benchmark_payload: Parameter input untuk routine ini.
        concurrency_payload: Parameter input untuk routine ini.
        observability_payload: Parameter input untuk routine ini.
        generated_day: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    benchmark_results = list(benchmark_payload.get("results") or [])
    concurrency_results = list(concurrency_payload.get("results") or [])
    benchmark_failures = list(benchmark_payload.get("failures") or [])
    concurrency_failures = list(concurrency_payload.get("failures") or [])

    bench_thresholds = dict(benchmark_payload.get("thresholds") or {})
    conc_thresholds = dict(concurrency_payload.get("thresholds") or {})
    bench_max_p95 = float(bench_thresholds.get("max_p95_ms") or 0.0)
    bench_max_max = float(bench_thresholds.get("max_max_ms") or 0.0)
    conc_max_p95 = float(conc_thresholds.get("max_p95_ms") or 0.0)
    conc_max_max = float(conc_thresholds.get("max_max_ms") or 0.0)

    benchmark_pass_count = 0
    for row in benchmark_results:
        p95 = float(row.get("p95_ms") or 0.0)
        max_latency = float(row.get("max_ms") or 0.0)
        passes_p95 = bench_max_p95 <= 0.0 or p95 <= bench_max_p95
        passes_max = bench_max_max <= 0.0 or max_latency <= bench_max_max
        if passes_p95 and passes_max:
            benchmark_pass_count += 1

    concurrency_pass_count = 0
    total_concurrency_requests = 0
    failed_concurrency_requests = 0
    for row in concurrency_results:
        p95 = float(row.get("p95_ms") or 0.0)
        max_latency = float(row.get("max_ms") or 0.0)
        status_failures = list(row.get("failures") or [])
        requests_count = int(row.get("requests") or 0)
        total_concurrency_requests += requests_count
        failed_concurrency_requests += len(status_failures)
        passes_p95 = conc_max_p95 <= 0.0 or p95 <= conc_max_p95
        passes_max = conc_max_max <= 0.0 or max_latency <= conc_max_max
        if not status_failures and passes_p95 and passes_max:
            concurrency_pass_count += 1

    expected_endpoints = list(observability_payload.get("expected_endpoints") or [])
    missing_requests = list(observability_payload.get("missing_requests") or [])
    missing_rows = list(observability_payload.get("missing_rows") or [])
    covered_endpoints = max(len(expected_endpoints) - len(set(missing_requests + missing_rows)), 0)

    week_start, week_end = _week_range(generated_day)
    success_requests = max(total_concurrency_requests - failed_concurrency_requests, 0)
    request_success_rate = _ratio_percentage(success_requests, total_concurrency_requests)
    benchmark_latency_compliance = _ratio_percentage(benchmark_pass_count, len(benchmark_results))
    concurrency_latency_compliance = _ratio_percentage(concurrency_pass_count, len(concurrency_results))
    observability_coverage = _ratio_percentage(covered_endpoints, len(expected_endpoints))

    return {
        "generated_day": generated_day.isoformat(),
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "signals": {
            "benchmark_latency_compliance_pct": round(benchmark_latency_compliance, 2),
            "concurrency_latency_compliance_pct": round(concurrency_latency_compliance, 2),
            "concurrency_request_success_pct": round(request_success_rate, 2),
            "observability_coverage_pct": round(observability_coverage, 2),
        },
        "raw_counts": {
            "benchmark_endpoints_total": len(benchmark_results),
            "benchmark_endpoints_passed": benchmark_pass_count,
            "benchmark_failure_entries": len(benchmark_failures),
            "concurrency_paths_total": len(concurrency_results),
            "concurrency_paths_passed": concurrency_pass_count,
            "concurrency_failure_entries": len(concurrency_failures),
            "concurrency_requests_total": total_concurrency_requests,
            "concurrency_requests_failed": failed_concurrency_requests,
            "observability_expected_endpoints": len(expected_endpoints),
            "observability_endpoints_covered": covered_endpoints,
        },
    }


def _build_weekly_sla_markdown(sla_summary: dict[str, Any]) -> str:
    """Build weekly sla markdown.

    Args:
        sla_summary: Parameter input untuk routine ini.

    Returns:
        TODO describe return value.

    """
    signals = dict(sla_summary.get("signals") or {})
    counts = dict(sla_summary.get("raw_counts") or {})
    lines = [
        "# Weekly Baseline SLA Report",
        "",
        f"- Week range: {sla_summary.get('week_start')} -> {sla_summary.get('week_end')}",
        f"- Generated day: {sla_summary.get('generated_day')}",
        "",
        "## Baseline Signals",
        "",
        f"- Benchmark latency compliance: {float(signals.get('benchmark_latency_compliance_pct') or 0.0):.2f}%",
        f"- Concurrency latency compliance: {float(signals.get('concurrency_latency_compliance_pct') or 0.0):.2f}%",
        f"- Concurrency request success: {float(signals.get('concurrency_request_success_pct') or 0.0):.2f}%",
        f"- Observability payload coverage: {float(signals.get('observability_coverage_pct') or 0.0):.2f}%",
        "",
        "## Raw Counts",
        "",
        f"- Benchmark endpoints passed/total: {counts.get('benchmark_endpoints_passed', 0)}/{counts.get('benchmark_endpoints_total', 0)}",
        f"- Concurrency paths passed/total: {counts.get('concurrency_paths_passed', 0)}/{counts.get('concurrency_paths_total', 0)}",
        f"- Concurrency request failed/total: {counts.get('concurrency_requests_failed', 0)}/{counts.get('concurrency_requests_total', 0)}",
        f"- Observability covered/expected: {counts.get('observability_endpoints_covered', 0)}/{counts.get('observability_expected_endpoints', 0)}",
        "",
        "## Notes",
        "",
        "- Report ini baseline mingguan dari artifact non-functional smoke.",
        "- Gunakan baseline ini untuk mendeteksi drift performa/coverage antar minggu.",
        "",
    ]
    return "\n".join(lines).strip() + "\n"


def _write_text(path: Path, payload: str) -> None:
    """Perform write text.

    Args:
        path: Parameter input untuk routine ini.
        payload: Parameter input untuk routine ini.

    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Perform write json.

    Args:
        path: Parameter input untuk routine ini.
        payload: Parameter input untuk routine ini.

    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def main() -> None:
    """Run the module entrypoint.

    Returns:
        Nilai balik routine atau efek samping yang dihasilkan.

    """
    parser = argparse.ArgumentParser(description="Generate non-functional triage and weekly SLA reports.")
    parser.add_argument("--artifacts-dir", default=".ci_artifacts", help="Directory containing JSON smoke artifacts.")
    parser.add_argument(
        "--triage-output",
        default=".ci_artifacts/nonfunctional_triage.md",
        help="Output markdown path for triage summary.",
    )
    parser.add_argument(
        "--sla-output",
        default=".ci_artifacts/weekly_sla_baseline.md",
        help="Output markdown path for weekly SLA baseline report.",
    )
    parser.add_argument(
        "--sla-json-output",
        default=".ci_artifacts/weekly_sla_baseline.json",
        help="Output JSON path for weekly SLA baseline report.",
    )
    args = parser.parse_args()

    artifacts_dir = Path(str(args.artifacts_dir or ".ci_artifacts"))
    benchmark_payload = _load_json(artifacts_dir / "benchmark.json")
    concurrency_payload = _load_json(artifacts_dir / "concurrency.json")
    observability_payload = _load_json(artifacts_dir / "observability_payload.json")

    now_utc = datetime.now(UTC)
    triage_markdown = _build_triage_markdown(
        benchmark_payload=benchmark_payload,
        concurrency_payload=concurrency_payload,
        observability_payload=observability_payload,
        generated_at=now_utc,
    )
    sla_summary = _build_sla_summary(
        benchmark_payload=benchmark_payload,
        concurrency_payload=concurrency_payload,
        observability_payload=observability_payload,
        generated_day=now_utc.date(),
    )
    sla_markdown = _build_weekly_sla_markdown(sla_summary)

    _write_text(Path(str(args.triage_output)), triage_markdown)
    _write_text(Path(str(args.sla_output)), sla_markdown)
    _write_json(Path(str(args.sla_json_output)), sla_summary)


if __name__ == "__main__":
    main()
