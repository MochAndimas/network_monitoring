import json
from types import SimpleNamespace

from backend.app.bandwidth import profiling


def test_profile_is_aggregated_rate_limited_and_resets(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(profiling, "perf_counter", lambda: clock[0])
    messages = []
    logger = SimpleNamespace(info=lambda fmt, value: messages.append((fmt, json.loads(value))))
    profile = profiling.IngestionProfiler(2, logger)
    report = SimpleNamespace(accepted=10, rejected=2)
    profile.observe({"resolve_clients_ms": 5}, 10, report)
    assert not messages
    clock[0] = 61
    profile.observe({"commit_ms": 3}, 7, None, failed=True)
    payload = messages[0][1]
    assert payload["calls"] == 2 and payload["errors"] == 1
    assert payload["accepted"] == 10 and payload["rejected"] == 2
    assert payload["phase_ms"] == {"resolve_clients_ms": 5, "commit_ms": 3, "total_ms": 17}
    clock[0] = 122
    profile.observe({}, 1, None)
    assert messages[1][1]["calls"] == 1
    assert messages[1][1]["accepted"] == 0
    assert messages[1][1]["idle_calls"] == 1


def test_phase_timer_accumulates_only_elapsed_metadata(monkeypatch):
    clock = iter([1.0, 1.25, 1.75])
    monkeypatch.setattr(profiling, "perf_counter", lambda: next(clock))
    timings = {}
    timer = profiling.PhaseTimer(timings)
    timer.mark("resolve_clients_ms")
    timer.mark("commit_ms")
    assert timings == {"resolve_clients_ms": 250, "commit_ms": 500}
