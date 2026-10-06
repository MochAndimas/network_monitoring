"""notifiers support code for telegram notifier."""

from __future__ import annotations

import logging
from typing import Protocol

from ...core.config import settings
from ...core.settings_groups import TelegramSettings
from .base import NotificationResult

try:
    from telegram import Bot
except ImportError:  # pragma: no cover
    Bot = None  # type: ignore[assignment, misc]


logger = logging.getLogger("network_monitoring.telegram")


class TelegramTransport(Protocol):
    async def __call__(self, *, token: str, chat_id: str, message: str) -> None: ...


async def send_telegram_message(*, token: str, chat_id: str, message: str) -> None:
    if Bot is None:
        raise RuntimeError("Telegram transport unavailable")
    async with Bot(token=token) as bot:
        await bot.send_message(chat_id=chat_id, text=message)


class TelegramNotifier:
    """Telegram implementation of the generic alert-notifier contract."""

    channel = "telegram"

    def __init__(self, *, config: TelegramSettings | None = None, transport: TelegramTransport | None = None) -> None:
        self.config = config
        self.transport = transport or send_telegram_message
        self.transport_available = transport is not None or Bot is not None

    async def send(self, message: str) -> NotificationResult:
        """Send one Telegram message and retain only a safe outcome category."""
        telegram_settings = self.config if self.config is not None else settings.telegram
        if not telegram_settings.bot_token or not telegram_settings.chat_id or not self.transport_available:
            logger.info("Telegram notifier is not configured; alert skipped")
            return NotificationResult(False, self.channel, "configuration_missing")

        try:
            await self.transport(token=telegram_settings.bot_token, chat_id=telegram_settings.chat_id, message=message)
        except Exception:
            logger.warning("Telegram alert delivery_failed")
            return NotificationResult(False, self.channel, "delivery_failed")

        logger.info("Telegram alert sent")
        return NotificationResult(True, self.channel)


async def send_telegram_alert(message: str) -> bool:
    """Compatibility wrapper used by the current alert engine and its tests."""
    return (await TelegramNotifier().send(message)).accepted
