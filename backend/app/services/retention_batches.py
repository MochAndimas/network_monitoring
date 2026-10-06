"""Shared bounded deletion and explicit transaction ownership for retention."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql.elements import ColumnElement

from ..core.config import settings


async def finish_retention_batch(db: AsyncSession, commit: bool) -> None:
    if commit:
        await db.commit()
    else:
        await db.flush()


async def delete_rows_in_batches(
    db: AsyncSession, model: type[DeclarativeBase], condition: ColumnElement[bool], *, commit: bool
) -> int:
    total = 0
    # The supported models all expose an integer primary key.
    id_column = model.__table__.c.id
    for _ in range(settings.retention.max_batches_per_phase):
        ids = list(
            (
                await db.scalars(
                    select(id_column).where(condition).order_by(id_column).limit(settings.retention.delete_batch_size)
                )
            ).all()
        )
        if not ids:
            await finish_retention_batch(db, commit)
            break
        result = await db.execute(
            delete(model).where(id_column.in_(ids), condition).execution_options(synchronize_session=False)
        )
        count = int(getattr(result, "rowcount", 0) or 0)
        await finish_retention_batch(db, commit)
        total += count
    return total
