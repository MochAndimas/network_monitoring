"""Define module logic for `backend/app/alerting/notifiers/telegram_notifier.py`.

This module contains project-specific implementation details.
"""

from __future__ import annotations

import logging

from ...core.config import settings

try:
    from telegram import Bot
except ImportError:  # pragma: no cover
    Bot = None  # type: ignore[assignment, misc]


logger = logging.getLogger("network_monitoring.telegram")


async def send_telegram_alert(message: str) -> None:
    """Return send telegram alert.

    Args:
        message: Parameter input untuk routine ini.

    """
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
