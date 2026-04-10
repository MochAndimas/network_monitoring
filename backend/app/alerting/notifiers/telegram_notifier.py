from __future__ import annotations

import asyncio

from ...core.config import settings

try:
    from telegram import Bot
except ImportError:  # pragma: no cover
    Bot = None


def send_telegram_alert(message: str) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id or Bot is None:
        print(f"[TELEGRAM ALERT] {message}")
        return

    async def _send() -> None:
        bot = Bot(token=settings.telegram_bot_token)
        await bot.send_message(chat_id=settings.telegram_chat_id, text=message)

    try:
        asyncio.run(_send())
    except RuntimeError:
        print(f"[TELEGRAM ALERT] {message}")
        return

    print(f"[TELEGRAM ALERT] {message}")
