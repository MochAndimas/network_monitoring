"""Service-layer workflows for device service."""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..repositories.device_repository import DeviceRepository
from .dashboard_overview_service import invalidate_dashboard_overview_cache


async def list_device_rows_filtered(
    db: AsyncSession,
    *,
    active_only: bool = False,
    device_type: str | None = None,
    latest_status: str | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    """List device rows filtered in the service layer."""
    return await DeviceRepository(db).list_device_status_rows(
        active_only=active_only,
        device_type=device_type,
        latest_status=latest_status,
        search=search,
        limit=limit,
        offset=offset,
    )


async def get_device_row(db: AsyncSession, device_id: int) -> dict:
    """Return get device row used by device inventory and status."""
    rows = await DeviceRepository(db).list_device_status_rows(device_id=device_id)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return rows[0]


async def create_device(db: AsyncSession, payload: dict, *, commit: bool = True):
    """Create device in the service layer."""
    payload = {**payload, "site": str(payload.get("site") or "").strip()}
    if not payload["site"]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="site is required")
    repository = DeviceRepository(db)
    existing = await repository.get_by_ip_address(payload["ip_address"])
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="IP address already exists")
    device = await repository.create_device(payload, commit=commit)
    invalidate_dashboard_overview_cache()
    return device


async def update_device(db: AsyncSession, device_id: int, payload: dict, *, commit: bool = True):
    """Update device in the service layer."""
    repository = DeviceRepository(db)
    device = await repository.get_by_id(device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    if "site" in payload:
        payload = {**payload, "site": str(payload.get("site") or "").strip()}
        if not payload["site"]:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="site is required")

    ip_address = payload.get("ip_address")
    if ip_address:
        existing = await repository.get_by_ip_address(ip_address)
        if existing is not None and existing.id != device_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="IP address already exists")

    updated_device = await repository.update_device(device, payload, commit=commit)
    invalidate_dashboard_overview_cache()
    return updated_device


async def delete_device(db: AsyncSession, device_id: int, *, commit: bool = True) -> None:
    """Delete device in the service layer."""
    repository = DeviceRepository(db)
    device = await repository.get_by_id(device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    await repository.delete_device(device, commit=commit)
    invalidate_dashboard_overview_cache()
