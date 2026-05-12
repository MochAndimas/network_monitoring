"""Monitoring collector helpers for service."""

from __future__ import annotations

import asyncio
from time import perf_counter

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...repositories.device_repository import DeviceRepository
from ...repositories.metric_repository import MetricRepository
from ...core.time import utcnow
from ..helpers import bounded_gather, build_ping_metric, build_ping_quality_metrics, collect_ping_samples, latest_successful_ping


async def run_internet_checks(db: AsyncSession) -> list[dict]:
    """Run internet checks for monitoring collection."""
    devices = await DeviceRepository(db).list_by_type("internet_target", active_only=True)
    metrics: list[dict] = []
    if devices:
        metrics.extend(
            metric
            for device_metrics in await bounded_gather(
                [_build_device_ping_metrics(device.id, device.ip_address) for device in devices]
            )
            for metric in device_metrics
        )

    if devices:
        anchor_device = _select_internet_anchor_device(devices)
        async with httpx.AsyncClient(timeout=settings.http_check_timeout_seconds) as client:
            dns_metric, http_metric, public_ip_metric = await asyncio.gather(
                _build_dns_metric(anchor_device.id),
                _build_http_metric(anchor_device.id, client),
                _build_public_ip_metric(db, anchor_device.id, client),
            )
            metrics.extend([dns_metric, http_metric, public_ip_metric])

    return metrics


def _select_internet_anchor_device(devices):
    """Return select internet anchor device for monitoring collection."""
    def priority(device) -> tuple[int, str]:
        name = str(getattr(device, "name", "") or "").lower()
        if "myrepublic" in name:
            return (0, name)
        if "isp" in name:
            return (1, name)
        if "mikrotik" in name:
            return (3, name)
        return (2, name)

    return min(devices, key=priority)


async def _build_device_ping_metrics(device_id: int, ip_address: str) -> list[dict]:
    """Build device ping metrics for monitoring collection."""
    samples = await collect_ping_samples(ip_address)
    return [
        build_ping_metric(device_id, latest_successful_ping(samples)),
        *build_ping_quality_metrics(device_id, samples),
    ]


async def _build_dns_metric(device_id: int) -> dict:
    """Build dns metric for monitoring collection."""
    checked_at = utcnow()
    started_at = perf_counter()
    try:
        await asyncio.get_running_loop().getaddrinfo(settings.dns_check_host, None)
    except OSError:
        return {
            "device_id": device_id,
            "metric_name": "dns_resolution_time",
            "metric_value": "failed",
            "status": "down",
            "unit": None,
            "checked_at": checked_at,
        }

    elapsed_ms = (perf_counter() - started_at) * 1000
    return {
        "device_id": device_id,
        "metric_name": "dns_resolution_time",
        "metric_value": f"{elapsed_ms:.2f}",
        "status": "up",
        "unit": "ms",
        "checked_at": checked_at,
    }


async def _build_http_metric(device_id: int, client: httpx.AsyncClient) -> dict:
    """Build http metric for monitoring collection."""
    checked_at = utcnow()
    started_at = perf_counter()
    try:
        response = await _get_with_retries(client, settings.http_check_url)
    except httpx.HTTPError:
        return {
            "device_id": device_id,
            "metric_name": "http_response_time",
            "metric_value": "failed",
            "status": "down",
            "unit": None,
            "checked_at": checked_at,
        }

    elapsed_ms = (perf_counter() - started_at) * 1000
    return {
        "device_id": device_id,
        "metric_name": "http_response_time",
        "metric_value": f"{elapsed_ms:.2f}",
        "status": "up",
        "unit": "ms",
        "checked_at": checked_at,
    }


async def _build_public_ip_metric(db: AsyncSession, device_id: int, client: httpx.AsyncClient) -> dict:
    """Build public ip metric for monitoring collection."""
    checked_at = utcnow()
    try:
        response = await _get_with_retries(client, settings.public_ip_check_url)
        public_ip = response.text.strip()
    except httpx.HTTPError:
        return {
            "device_id": device_id,
            "metric_name": "public_ip",
            "metric_value": "unavailable",
            "status": "down",
            "unit": None,
            "checked_at": checked_at,
        }

    latest_public_ip = await MetricRepository(db).get_latest_valid_public_ip_metric(device_id)
    status = "warning" if latest_public_ip is not None and latest_public_ip.metric_value != public_ip else "up"
    return {
        "device_id": device_id,
        "metric_name": "public_ip",
        "metric_value": public_ip,
        "status": status,
        "unit": None,
        "checked_at": checked_at,
    }


async def _get_with_retries(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """GET a URL with a small retry budget for transient internet check failures."""
    attempts = max(int(settings.http_check_retries or 1), 1)
    last_error: httpx.HTTPError | None = None
    for attempt in range(attempts):
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt < attempts - 1:
                await asyncio.sleep(0.25)
    if last_error is not None:
        raise last_error
    raise httpx.RequestError("HTTP check failed without a response")
