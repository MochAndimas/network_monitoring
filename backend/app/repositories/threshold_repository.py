"""Define module logic for `backend/app/repositories/threshold_repository.py`.

This module contains project-specific implementation details.
"""

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.threshold import Threshold


class ThresholdRepository:
    """Perform ThresholdRepository.

    This class encapsulates related behavior and data for this domain area.
    """
    def __init__(self, db: AsyncSession):
        """Perform init.

        Args:
            db: Parameter input untuk routine ini.

        Returns:
            TODO describe return value.

        """
        self.db = db

    async def list_thresholds(self) -> list[Threshold]:
        """Repository method to list thresholds.

        Returns:
            TODO describe return value.

        """
        query: Select[tuple[Threshold]] = select(Threshold).order_by(Threshold.key.asc())
        return list((await self.db.scalars(query)).all())

    async def count_thresholds(self) -> int:
        """Repository method to count thresholds.

        Returns:
            TODO describe return value.

        """
        query = select(func.count()).select_from(Threshold)
        return int(await self.db.scalar(query) or 0)

    async def get_by_key(self, key: str) -> Threshold | None:
        """Repository method to get by key.

        Args:
            key: Parameter input untuk routine ini.

        Returns:
            TODO describe return value.

        """
        query: Select[tuple[Threshold]] = select(Threshold).where(Threshold.key == key)
        return (await self.db.scalars(query)).first()

    async def upsert_threshold(self, key: str, value: float, description: str | None = None, *, commit: bool = True) -> Threshold:
        """Repository method to upsert threshold.

        Args:
            key: Parameter input untuk routine ini.
            value: Parameter input untuk routine ini.
            description: Parameter input untuk routine ini.
            commit: Parameter input untuk routine ini.

        Returns:
            TODO describe return value.

        """
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
