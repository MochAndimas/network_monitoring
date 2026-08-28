"""Monitoring collector helpers for helpers."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass

from ping3 import ping

from ..core.config import settings
from ..core.time import utcnow
from .contracts import collection_metric_status, normalize_collection_status


PING_SEMAPHORE = asyncio.Semaphore(max(settings.monitor.ping_concurrency_limit, 1))
_VENDOR_PROTOCOL_SEMAPHORES: dict[str, asyncio.Semaphore] = {}


@dataclass(frozen=True)
class PingProbeResult:
    """One ICMP probe result, including whether the local collector worked."""

    latency_seconds: float | None
    collection_status: str


def build_ping_metric(device_id: int, latency_seconds: float | None) -> dict:
    """Build ping metric for monitoring collection."""
    checked_at = utcnow()
    if latency_seconds is None:
        return {
            "device_id": device_id,
            "metric_name": "ping",
            "metric_value": "timeout",
            "status": "down",
            "unit": None,
            "checked_at": checked_at,
        }

    return {
        "device_id": device_id,
        "metric_name": "ping",
        "metric_value": f"{latency_seconds * 1000:.2f}",
        "status": "up",
        "unit": "ms",
        "checked_at": checked_at,
    }


def build_ping_quality_metrics(device_id: int, samples: list[float | None]) -> list[dict]:
    """Build ping quality metrics for monitoring collection."""
    checked_at = utcnow()
    sample_count = len(samples)
    lost_count = sum(sample is None for sample in samples)
    packet_loss = (lost_count / sample_count) * 100 if sample_count else 100
    successful_samples = [sample for sample in samples if sample is not None]
    jitter_ms = _calculate_jitter_ms(successful_samples)
    status = "down" if lost_count == sample_count else "warning" if lost_count else "up"

    return [
        {
            "device_id": device_id,
            "metric_name": "packet_loss",
            "metric_value": f"{packet_loss:.2f}",
            "status": status,
            "unit": "%",
            "checked_at": checked_at,
        },
        {
            "device_id": device_id,
            "metric_name": "jitter",
            "metric_value": f"{jitter_ms:.2f}" if jitter_ms is not None else "unavailable",
            "status": status,
            "unit": "ms" if jitter_ms is not None else None,
            "checked_at": checked_at,
        },
    ]


async def collect_ping_samples(ip_address: str) -> list[float | None]:
    """Collect ping samples for monitoring collection."""
    sample_count = max(settings.monitor.ping_sample_count, 1)
    return list(await asyncio.gather(*[safe_ping(ip_address) for _ in range(sample_count)]))


async def collect_ping_probe_samples(ip_address: str) -> list[PingProbeResult]:
    """Collect ICMP probes while separating a target timeout from a local failure."""
    sample_count = max(settings.monitor.ping_sample_count, 1)
    return list(await asyncio.gather(*[_collect_ping_probe(ip_address) for _ in range(sample_count)]))


async def _collect_ping_probe(ip_address: str) -> PingProbeResult:
    """Run one probe and retain only a safe collector error category."""
    try:
        return PingProbeResult(latency_seconds=await safe_ping(ip_address), collection_status="ok")
    except asyncio.TimeoutError:
        return PingProbeResult(latency_seconds=None, collection_status="timeout")
    except OSError:
        return PingProbeResult(latency_seconds=None, collection_status="connection_failed")
    except Exception:
        return PingProbeResult(latency_seconds=None, collection_status="collector_error")


def build_ping_check_metrics(device_id: int, probes: list[PingProbeResult]) -> list[dict]:
    """Build reachability metrics without treating a collector failure as target down."""
    checked_at = utcnow()
    collection_status = _ping_collection_status(probes)
    collection_metric = {
        "device_id": device_id,
        "metric_name": "ping_collection_status",
        "metric_value": normalize_collection_status(collection_status),
        "status": collection_metric_status(collection_status),
        "unit": "icmp",
        "checked_at": checked_at,
    }
    if normalize_collection_status(collection_status) != "ok":
        unavailable = {
            "device_id": device_id,
            "metric_value": "unavailable",
            "status": "warning",
            "unit": None,
            "checked_at": checked_at,
        }
        return [
            collection_metric,
            {**unavailable, "metric_name": "ping"},
            {**unavailable, "metric_name": "packet_loss"},
            {**unavailable, "metric_name": "jitter"},
        ]

    samples = [probe.latency_seconds for probe in probes]
    return [
        collection_metric,
        build_ping_metric(device_id, latest_successful_ping(samples)),
        *build_ping_quality_metrics(device_id, samples),
    ]


def _ping_collection_status(probes: list[PingProbeResult]) -> str:
    """Return a canonical collector state; ICMP non-response is still a valid probe."""
    if any(probe.collection_status == "ok" for probe in probes):
        return "ok"
    for category in ("timeout", "connection_failed", "collector_error"):
        if any(probe.collection_status == category for probe in probes):
            return category
    return "collector_error"


def latest_successful_ping(samples: list[float | None]) -> float | None:
    """Return latest latest successful ping used by monitoring collection."""
    successful_samples = [sample for sample in samples if sample is not None]
    return successful_samples[-1] if successful_samples else None


async def safe_ping(ip_address: str) -> float | None:
    """Return one raw ping result; callers should use the probe contract for errors."""
    async with PING_SEMAPHORE:
        return await asyncio.to_thread(ping, ip_address, timeout=int(settings.monitor.ping_timeout_seconds))


async def bounded_gather(coroutines, *, limit: int | None = None) -> list:
    """Run bounded gather for monitoring collection."""
    coroutines = list(coroutines)
    if not coroutines:
        return []
    concurrency_limit = max(limit or settings.monitor.task_concurrency_limit, 1)
    semaphore = asyncio.Semaphore(concurrency_limit)

    async def _run(coroutine):
        async with semaphore:
            return await coroutine

    return list(await asyncio.gather(*[_run(coroutine) for coroutine in coroutines]))


@asynccontextmanager
async def vendor_protocol_guard(vendor_protocol: str, *, limit: int | None = None):
    """Bound concurrent requests to one fragile vendor/protocol combination."""
    key = str(vendor_protocol or "default").strip().lower() or "default"
    semaphore = _VENDOR_PROTOCOL_SEMAPHORES.get(key)
    if semaphore is None:
        semaphore = asyncio.Semaphore(max(limit or settings.monitor.snmp_concurrency_limit, 1))
        _VENDOR_PROTOCOL_SEMAPHORES[key] = semaphore
    async with semaphore:
        yield


async def retry_transient_collection(operation, *, retryable_statuses: set[str]):
    """Retry a bounded number of transient collector outcomes with backoff."""
    attempts = max(settings.monitor.collector_retry_attempts, 1)
    result = await operation()
    for attempt in range(1, attempts):
        if getattr(result, "collection_status", None) not in retryable_statuses:
            break
        await asyncio.sleep(settings.monitor.collector_retry_backoff_seconds * attempt)
        result = await operation()
    return result


def _calculate_jitter_ms(samples: list[float]) -> float | None:
    """Return calculate jitter ms for monitoring collection."""
    if len(samples) < 2:
        return 0.0 if samples else None

    deltas = [abs(samples[index] - samples[index - 1]) * 1000 for index in range(1, len(samples))]
    return sum(deltas) / len(deltas)
