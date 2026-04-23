"""Provide alert evaluation and notification workflows for the network monitoring project."""

from __future__ import annotations

import logging

from ...core.config import settings

try:
    from telegram import Bot
except ImportError:  # pragma: no cover
    Bot = None


logger = logging.getLogger("network_monitoring.telegram")


async def send_telegram_alert(message: str) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id or Bot is None:
        logger.info("Telegram notifier is not configured; alert skipped: %s", message)
        return

    try:
        bot = Bot(token=settings.telegram_bot_token)
        await bot.send_message(chat_id=settings.telegram_chat_id, text=message)
    except Exception:
        logger.exception("Telegram alert could not be sent")
        return

    logger.info("Telegram alert sent")
