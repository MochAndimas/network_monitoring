"""Define API lifecycle policy and deprecation metadata for legacy contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import Response


@dataclass(frozen=True)
class LegacyEndpointDeprecation:
    """Store deprecation lifecycle metadata for one legacy endpoint."""

    legacy_endpoint: str
    replacement_endpoint: str
    announced_on: date
    warning_window_starts_on: date
    removal_on: date
    sunset_http_date: str


LEGACY_NON_PAGED_DEPRECATION_PLAN: dict[str, LegacyEndpointDeprecation] = {
    "/devices": LegacyEndpointDeprecation(
        legacy_endpoint="/devices",
        replacement_endpoint="/devices/paged",
        announced_on=date(2026, 4, 24),
        warning_window_starts_on=date(2026, 5, 1),
        removal_on=date(2026, 10, 31),
        sunset_http_date="Sat, 31 Oct 2026 00:00:00 GMT",
    ),
    "/alerts/active": LegacyEndpointDeprecation(
        legacy_endpoint="/alerts/active",
        replacement_endpoint="/alerts/active/paged",
        announced_on=date(2026, 4, 24),
        warning_window_starts_on=date(2026, 5, 1),
        removal_on=date(2026, 10, 31),
        sunset_http_date="Sat, 31 Oct 2026 00:00:00 GMT",
    ),
    "/incidents": LegacyEndpointDeprecation(
        legacy_endpoint="/incidents",
        replacement_endpoint="/incidents/paged",
        announced_on=date(2026, 4, 24),
        warning_window_starts_on=date(2026, 5, 1),
        removal_on=date(2026, 10, 31),
        sunset_http_date="Sat, 31 Oct 2026 00:00:00 GMT",
    ),
    "/metrics/history": LegacyEndpointDeprecation(
        legacy_endpoint="/metrics/history",
        replacement_endpoint="/metrics/history/paged",
        announced_on=date(2026, 4, 24),
        warning_window_starts_on=date(2026, 5, 1),
        removal_on=date(2026, 10, 31),
        sunset_http_date="Sat, 31 Oct 2026 00:00:00 GMT",
    ),
}


def _deprecation_phase(*, plan: LegacyEndpointDeprecation, today: date) -> str:
    if today >= plan.removal_on:
        return "removal"
    if today >= plan.warning_window_starts_on:
        return "warning"
    return "announce"


def apply_legacy_deprecation_headers(response: Response, *, legacy_endpoint: str, today: date | None = None) -> None:
    """Attach standard deprecation headers for a legacy API endpoint response."""

    plan = LEGACY_NON_PAGED_DEPRECATION_PLAN[legacy_endpoint]
    evaluated_on = today or date.today()
    phase = _deprecation_phase(plan=plan, today=evaluated_on)
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = plan.sunset_http_date
    response.headers["Warning"] = (
        '299 - "Deprecated API endpoint. '
        f"Migrate from {plan.legacy_endpoint} to {plan.replacement_endpoint} before {plan.removal_on.isoformat()}.\""
    )
    response.headers["X-API-Deprecation-Phase"] = phase
    response.headers["X-API-Deprecation-Announced-On"] = plan.announced_on.isoformat()
    response.headers["X-API-Deprecation-Warning-Window-Starts-On"] = plan.warning_window_starts_on.isoformat()
    response.headers["X-API-Deprecation-Removal-On"] = plan.removal_on.isoformat()
    response.headers["X-API-Replacement-Endpoint"] = plan.replacement_endpoint
