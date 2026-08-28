"""notifiers support code for telegram notifier."""

from __future__ import annotations

import logging

from ...core.config import settings
from .base import NotificationResult

try:
    from telegram import Bot
except ImportError:  # pragma: no cover
    Bot = None  # type: ignore[assignment, misc]


logger = logging.getLogger("network_monitoring.telegram")


class TelegramNotifier:
    """Telegram implementation of the generic alert-notifier contract."""

    channel = "telegram"

    async def send(self, message: str) -> NotificationResult:
        """Send one Telegram message and retain only a safe outcome category."""
        telegram_settings = settings.telegram
        if not telegram_settings.bot_token or not telegram_settings.chat_id or Bot is None:
            logger.info("Telegram notifier is not configured; alert skipped")
            return NotificationResult(False, self.channel, "configuration_missing")

        try:
            bot = Bot(token=telegram_settings.bot_token)
            await bot.send_message(chat_id=telegram_settings.chat_id, text=message)
        except Exception:
            logger.exception("Telegram alert could not be sent")
            return NotificationResult(False, self.channel, "delivery_failed")

        logger.info("Telegram alert sent")
        return NotificationResult(True, self.channel)


async def send_telegram_alert(message: str) -> bool:
    """Compatibility wrapper used by the current alert engine and its tests."""
    return (await TelegramNotifier().send(message)).accepted
