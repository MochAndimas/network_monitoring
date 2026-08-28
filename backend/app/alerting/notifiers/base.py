"""Stable notifier contract shared by alert-delivery channels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class NotificationResult:
    """Safe result returned by a delivery channel."""

    accepted: bool
    channel: str
    error_category: str | None = None


class AlertNotifier(Protocol):
    """A delivery channel for already-rendered alert messages."""

    channel: str

    async def send(self, message: str) -> NotificationResult:
        """Deliver one message without exposing credentials in the result."""
        ...
