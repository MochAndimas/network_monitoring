from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..repositories.device_repository import DeviceRepository


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
    return await DeviceRepository(db).list_device_status_rows(
        active_only=active_only,
        device_type=device_type,
        latest_status=latest_status,
        search=search,
        limit=limit,
        offset=offset,
    )


async def get_device_row(db: AsyncSession, device_id: int) -> dict:
    rows = await DeviceRepository(db).list_device_status_rows(device_id=device_id)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return rows[0]


async def create_device(db: AsyncSession, payload: dict):
    repository = DeviceRepository(db)
    existing = await repository.get_by_ip_address(payload["ip_address"])
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="IP address already exists")
    return await repository.create_device(payload)


async def update_device(db: AsyncSession, device_id: int, payload: dict):
    repository = DeviceRepository(db)
    device = await repository.get_by_id(device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    ip_address = payload.get("ip_address")
    if ip_address:
        existing = await repository.get_by_ip_address(ip_address)
        if existing is not None and existing.id != device_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="IP address already exists")

    return await repository.update_device(device, payload)


async def delete_device(db: AsyncSession, device_id: int) -> None:
    repository = DeviceRepository(db)
    device = await repository.get_by_id(device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    await repository.delete_device(device)
