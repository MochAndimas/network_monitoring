"""Database query helpers for threshold repository data."""

from datetime import datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.time import utcnow
from ..models.threshold import MaintenanceWindow, Threshold, ThresholdOverride


class ThresholdRepository:
    """Database access object for Threshold records."""
    def __init__(self, db: AsyncSession):
        """Initialize the object with its runtime dependencies."""
        self.db = db

    async def list_thresholds(self) -> list[Threshold]:
        """Query thresholds from the database."""
        query: Select[tuple[Threshold]] = select(Threshold).order_by(Threshold.key.asc())
        return list((await self.db.scalars(query)).all())

    async def count_thresholds(self) -> int:
        """Query thresholds from the database."""
        query = select(func.count()).select_from(Threshold)
        return int(await self.db.scalar(query) or 0)

    async def get_by_key(self, key: str) -> Threshold | None:
        """Return get by key used by threshold configuration."""
        query: Select[tuple[Threshold]] = select(Threshold).where(Threshold.key == key)
        return (await self.db.scalars(query)).first()

    async def upsert_threshold(self, key: str, value: float, description: str | None = None, *, commit: bool = True) -> Threshold:
        """Persist threshold changes in the database."""
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

    async def list_threshold_overrides(self, *, active_only: bool = False) -> list[ThresholdOverride]:
        """Return threshold overrides ordered by scope specificity."""
        query: Select[tuple[ThresholdOverride]] = select(ThresholdOverride).order_by(
            ThresholdOverride.threshold_key.asc(),
            ThresholdOverride.device_id.desc(),
            ThresholdOverride.device_type.desc(),
            ThresholdOverride.site.desc(),
            ThresholdOverride.id.asc(),
        )
        if active_only:
            query = query.where(ThresholdOverride.is_active.is_(True))
        return list((await self.db.scalars(query)).all())

    async def create_threshold_override(self, payload: dict, *, commit: bool = True) -> ThresholdOverride:
        """Create one scoped threshold override."""
        now = utcnow()
        override = ThresholdOverride(**payload, created_at=now, updated_at=now)
        self.db.add(override)
        await self.db.flush()
        if commit:
            await self.db.commit()
            await self.db.refresh(override)
        return override

    async def deactivate_threshold_override(self, override_id: int, *, commit: bool = True) -> bool:
        """Deactivate one threshold override by id."""
        override = await self.db.get(ThresholdOverride, override_id)
        if override is None:
            return False
        override.is_active = False
        override.updated_at = utcnow()
        await self.db.flush()
        if commit:
            await self.db.commit()
        return True

    async def list_maintenance_windows(self, *, active_only: bool = False) -> list[MaintenanceWindow]:
        """Return maintenance windows newest first."""
        query: Select[tuple[MaintenanceWindow]] = select(MaintenanceWindow).order_by(
            MaintenanceWindow.starts_at.desc(),
            MaintenanceWindow.id.desc(),
        )
        if active_only:
            current_time = utcnow()
            query = query.where(
                MaintenanceWindow.is_active.is_(True),
                MaintenanceWindow.starts_at <= current_time,
                MaintenanceWindow.ends_at >= current_time,
            )
        return list((await self.db.scalars(query)).all())

    async def create_maintenance_window(self, payload: dict, *, commit: bool = True) -> MaintenanceWindow:
        """Create one alert-suppression maintenance window."""
        now = utcnow()
        window = MaintenanceWindow(**payload, created_at=now, updated_at=now)
        self.db.add(window)
        await self.db.flush()
        if commit:
            await self.db.commit()
            await self.db.refresh(window)
        return window

    async def deactivate_maintenance_window(self, window_id: int, *, commit: bool = True) -> bool:
        """Deactivate one maintenance window by id."""
        window = await self.db.get(MaintenanceWindow, window_id)
        if window is None:
            return False
        window.is_active = False
        window.updated_at = utcnow()
        await self.db.flush()
        if commit:
            await self.db.commit()
        return True

    async def active_maintenance_windows_for_devices(
        self,
        *,
        device_ids: set[int],
        sites: set[str],
        current_time: datetime | None = None,
    ) -> list[MaintenanceWindow]:
        """Return active windows matching candidate devices or sites."""
        current_time = current_time or utcnow()
        conditions = []
        if device_ids:
            conditions.append(MaintenanceWindow.device_id.in_(device_ids))
        if sites:
            conditions.append(MaintenanceWindow.site.in_(sites))
        if not conditions:
            return []
        query = (
            select(MaintenanceWindow)
            .where(
                MaintenanceWindow.is_active.is_(True),
                MaintenanceWindow.starts_at <= current_time,
                MaintenanceWindow.ends_at >= current_time,
                or_(*conditions),
            )
            .order_by(MaintenanceWindow.starts_at.asc(), MaintenanceWindow.id.asc())
        )
        return list((await self.db.scalars(query)).all())
