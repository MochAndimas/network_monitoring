"""Provide database query and persistence repositories for the network monitoring project."""

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.threshold import Threshold


class ThresholdRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_thresholds(self) -> list[Threshold]:
        query: Select[tuple[Threshold]] = select(Threshold).order_by(Threshold.key.asc())
        return list((await self.db.scalars(query)).all())

    async def count_thresholds(self) -> int:
        query = select(func.count()).select_from(Threshold)
        return int(await self.db.scalar(query) or 0)

    async def get_by_key(self, key: str) -> Threshold | None:
        query: Select[tuple[Threshold]] = select(Threshold).where(Threshold.key == key)
        return (await self.db.scalars(query)).first()

    async def upsert_threshold(self, key: str, value: float, description: str | None = None, *, commit: bool = True) -> Threshold:
        threshold = await self.get_by_key(key)
        if threshold is None:
            threshold = Threshold(key=key, value=value, description=description)
            self.db.add(threshold)
        else:
            threshold.value = value
            threshold.description = description
        await self.db.flush()
        if commit:
            await self.db.commit()
        return threshold
