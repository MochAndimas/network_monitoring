"""Provide database query and persistence repositories for the network monitoring project."""

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.threshold import Threshold


class ThresholdRepository:
    """Represent threshold repository behavior and data for database query and persistence repositories.
    """
    def __init__(self, db: AsyncSession):
        """Handle the internal init helper logic for database query and persistence repositories.

        Args:
            db: db value used by this routine (type `AsyncSession`).

        Returns:
            The computed result, response payload, or side-effect outcome for the caller.
        """
        self.db = db

    async def list_thresholds(self) -> list[Threshold]:
        """Return a list of thresholds for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Returns:
            `list[Threshold]` result produced by the routine.
        """
        query: Select[tuple[Threshold]] = select(Threshold).order_by(Threshold.key.asc())
        return list((await self.db.scalars(query)).all())

    async def count_thresholds(self) -> int:
        """Count thresholds for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Returns:
            `int` result produced by the routine.
        """
        query = select(func.count()).select_from(Threshold)
        return int(await self.db.scalar(query) or 0)

    async def get_by_key(self, key: str) -> Threshold | None:
        """Return by key for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            key: key value used by this routine (type `str`).

        Returns:
            `Threshold | None` result produced by the routine.
        """
        query: Select[tuple[Threshold]] = select(Threshold).where(Threshold.key == key)
        return (await self.db.scalars(query)).first()

    async def upsert_threshold(self, key: str, value: float, description: str | None = None, *, commit: bool = True) -> Threshold:
        """Handle upsert threshold for database query and persistence repositories. This coroutine may perform asynchronous I/O or coordinate async dependencies.

        Args:
            key: key value used by this routine (type `str`).
            value: value value used by this routine (type `float`).
            description: description value used by this routine (type `str | None`, optional).
            commit: commit keyword value used by this routine (type `bool`, optional).

        Returns:
            `Threshold` result produced by the routine.
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
