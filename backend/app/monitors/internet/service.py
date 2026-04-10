from __future__ import annotations

import socket
from time import perf_counter

import httpx
from sqlalchemy.orm import Session

from ...core.config import settings
from ...repositories.device_repository import DeviceRepository
from ...repositories.metric_repository import MetricRepository
from ...services.monitoring_service import utcnow
from ..helpers import build_ping_metric, build_ping_quality_metrics, collect_ping_samples, latest_successful_ping


def run_internet_checks(db: Session) -> list[dict]:
    devices = DeviceRepository(db).list_by_type("internet_target", active_only=True)
    metrics: list[dict] = []

    for device in devices:
        samples = collect_ping_samples(device.ip_address)
        metrics.append(build_ping_metric(device.id, latest_successful_ping(samples)))
        metrics.extend(build_ping_quality_metrics(device.id, samples))

    if devices:
        anchor_device = devices[0]
        metrics.append(_build_dns_metric(anchor_device.id))
        metrics.append(_build_http_metric(anchor_device.id))
        metrics.append(_build_public_ip_metric(db, anchor_device.id))

    return metrics


def _build_dns_metric(device_id: int) -> dict:
    checked_at = utcnow()
    started_at = perf_counter()
    try:
        socket.getaddrinfo(settings.dns_check_host, None)
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


def _build_http_metric(device_id: int) -> dict:
    checked_at = utcnow()
    started_at = perf_counter()
    try:
        response = httpx.get(settings.http_check_url, timeout=settings.ping_timeout_seconds)
        response.raise_for_status()
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


def _build_public_ip_metric(db: Session, device_id: int) -> dict:
    checked_at = utcnow()
    try:
        response = httpx.get(settings.public_ip_check_url, timeout=settings.ping_timeout_seconds)
        response.raise_for_status()
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

    latest_public_ip = MetricRepository(db).latest_metric_map().get((device_id, "public_ip"))
    status = "warning" if latest_public_ip is not None and latest_public_ip.metric_value != public_ip else "up"
    return {
        "device_id": device_id,
        "metric_name": "public_ip",
        "metric_value": public_ip,
        "status": status,
        "unit": None,
        "checked_at": checked_at,
    }
