"""Bounded ingestion timing metadata; never include SQL, credentials or flow data."""

import json
from time import perf_counter


class PhaseTimer:
    def __init__(self, timings: dict[str, float] | None):
        self.timings = timings
        self.started = perf_counter()

    def mark(self, phase: str) -> None:
        now = perf_counter()
        if self.timings is not None:
            self.timings[phase] = self.timings.get(phase, 0.0) + (now - self.started) * 1000
        self.started = now


class IngestionProfiler:
    def __init__(self, router_id: int, logger, interval: float = 60):
        self.router_id, self.logger, self.interval = router_id, logger, interval
        self.started = perf_counter()
        self.totals: dict[str, float] = {}
        self.calls = self.errors = self.accepted = self.rejected = self.idle = 0

    def observe(self, timings, elapsed_ms, report, failed=False):
        self.calls += 1
        self.errors += int(failed)
        self.idle += int(report is None and not failed)
        if report is not None:
            self.accepted += report.accepted
            self.rejected += report.rejected
        for key, value in {**timings, "total_ms": elapsed_ms}.items():
            self.totals[key] = self.totals.get(key, 0.0) + value
        now = perf_counter()
        if now - self.started < self.interval:
            return
        payload = dict(
            router_id=self.router_id, window_seconds=round(now - self.started, 2),
            calls=self.calls, errors=self.errors, idle_calls=self.idle,
            accepted=self.accepted, rejected=self.rejected,
            phase_ms={key: round(value, 2) for key, value in self.totals.items()},
        )
        self.logger.info("flow_ingestion_profile %s", json.dumps(payload, sort_keys=True))
        self.started = now
        self.totals.clear()
        self.calls = self.errors = self.accepted = self.rejected = self.idle = 0
