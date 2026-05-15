"""notifiers support code for telegram notifier."""

from __future__ import annotations

import logging

from ...core.config import settings

try:
    from telegram import Bot
except ImportError:  # pragma: no cover
    Bot = None  # type: ignore[assignment, misc]


logger = logging.getLogger("network_monitoring.telegram")


async def send_telegram_alert(message: str) -> None:
    """Send telegram alert for alerting."""
    telegram_settings = settings.telegram
    if not telegram_settings.bot_token or not telegram_settings.chat_id or Bot is None:
        logger.info("Telegram notifier is not configured; alert skipped: %s", message)
        return

    try:
        bot = Bot(token=telegram_settings.bot_token)
        await bot.send_message(chat_id=telegram_settings.chat_id, text=message)
    except Exception:
        logger.exception("Telegram alert could not be sent")
        return

    logger.info("Telegram alert sent")
