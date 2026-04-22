"""Provide monitoring collectors for network, device, server, and Mikrotik metrics for the network monitoring project."""

from __future__ import annotations

import asyncio

from ping3 import ping

from ..core.config import settings
from ..core.time import utcnow


PING_SEMAPHORE = asyncio.Semaphore(max(settings.ping_concurrency_limit, 1))


def build_ping_metric(device_id: int, latency_seconds: float | None) -> dict:
    """Build ping metric for monitoring collectors for network, device, server, and Mikrotik metrics.

    Args:
        device_id: device id value used by this routine (type `int`).
        latency_seconds: latency seconds value used by this routine (type `float | None`).

    Returns:
        `dict` result produced by the routine.
    """
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
    """Build ping quality metrics for monitoring collectors for network, device, server, and Mikrotik metrics.

    Args:
        device_id: device id value used by this routine (type `int`).
        samples: samples value used by this routine (type `list[float | None]`).

    Returns:
        `list[dict]` result produced by the routine.
    """
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
    """Collect ping samples for monitoring collectors for network, device, server, and Mikrotik metrics. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        ip_address: ip address value used by this routine (type `str`).

    Returns:
        `list[float | None]` result produced by the routine.
    """
    sample_count = max(settings.ping_sample_count, 1)
    return list(await asyncio.gather(*[safe_ping(ip_address) for _ in range(sample_count)]))


def latest_successful_ping(samples: list[float | None]) -> float | None:
    """Handle latest successful ping for monitoring collectors for network, device, server, and Mikrotik metrics.

    Args:
        samples: samples value used by this routine (type `list[float | None]`).

    Returns:
        `float | None` result produced by the routine.
    """
    successful_samples = [sample for sample in samples if sample is not None]
    return successful_samples[-1] if successful_samples else None


async def safe_ping(ip_address: str) -> float | None:
    """Handle safe ping for monitoring collectors for network, device, server, and Mikrotik metrics. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        ip_address: ip address value used by this routine (type `str`).

    Returns:
        `float | None` result produced by the routine.
    """
    try:
        async with PING_SEMAPHORE:
            return await asyncio.to_thread(ping, ip_address, timeout=settings.ping_timeout_seconds)
    except OSError:
        return None


async def bounded_gather(coroutines, *, limit: int | None = None) -> list:
    """Handle bounded gather for monitoring collectors for network, device, server, and Mikrotik metrics. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        coroutines: coroutines value used by this routine.
        limit: limit keyword value used by this routine (type `int | None`, optional).

    Returns:
        `list` result produced by the routine.
    """
    coroutines = list(coroutines)
    if not coroutines:
        return []
    concurrency_limit = max(limit or settings.monitor_task_concurrency_limit, 1)
    semaphore = asyncio.Semaphore(concurrency_limit)

    async def _run(coroutine):
        """Run the requested operation for monitoring collectors for network, device, server, and Mikrotik metrics. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            coroutine: coroutine value used by this routine.

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
        async with semaphore:
            return await coroutine

    return list(await asyncio.gather(*[_run(coroutine) for coroutine in coroutines]))


def _calculate_jitter_ms(samples: list[float]) -> float | None:
    """Handle the internal calculate jitter ms helper logic for monitoring collectors for network, device, server, and Mikrotik metrics.

    Args:
        samples: samples value used by this routine (type `list[float]`).

    Returns:
        `float | None` result produced by the routine.
    """
    if len(samples) < 2:
        return 0.0 if samples else None

    deltas = [abs(samples[index] - samples[index - 1]) * 1000 for index in range(1, len(samples))]
    return sum(deltas) / len(deltas)
