"""Production alert evaluation always writes notifications transactionally."""

from sqlalchemy.ext.asyncio import AsyncSession
from ..alerting.engine_parts.impl import evaluate_alerts
from ..alerting.engine_parts.dependencies import AlertEvaluationDependencies
from ..core.config import settings
from .telegram_outbox_writer import TelegramOutboxWriter


async def _disabled_writer(db: AsyncSession, events: list[dict]) -> None:
    """Unconfigured Telegram must never fall back to inline transport."""


async def evaluate_operational_alerts(
    db: AsyncSession, *, commit: bool = True, dependencies: AlertEvaluationDependencies | None = None
) -> list[dict]:
    telegram = settings.telegram
    writer = TelegramOutboxWriter(telegram.chat_id) if telegram.chat_id else _disabled_writer
    return await evaluate_alerts(db, commit=commit, notification_writer=writer, dependencies=dependencies)
