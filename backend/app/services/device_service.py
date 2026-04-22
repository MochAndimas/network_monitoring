"""Provide business services that coordinate repositories and domain workflows for the network monitoring project."""

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
    """Return a list of device rows filtered for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        active_only: active only keyword value used by this routine (type `bool`, optional).
        device_type: device type keyword value used by this routine (type `str | None`, optional).
        latest_status: latest status keyword value used by this routine (type `str | None`, optional).
        search: search keyword value used by this routine (type `str | None`, optional).
        limit: limit keyword value used by this routine (type `int | None`, optional).
        offset: offset keyword value used by this routine (type `int`, optional).

    Returns:
        `list[dict]` result produced by the routine.
    """
    return await DeviceRepository(db).list_device_status_rows(
        active_only=active_only,
        device_type=device_type,
        latest_status=latest_status,
        search=search,
        limit=limit,
        offset=offset,
    )


async def get_device_row(db: AsyncSession, device_id: int) -> dict:
    """Return device row for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        device_id: device id value used by this routine (type `int`).

    Returns:
        `dict` result produced by the routine.
    """
    rows = await DeviceRepository(db).list_device_status_rows(device_id=device_id)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return rows[0]


async def create_device(db: AsyncSession, payload: dict):
    """Create device for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        payload: payload value used by this routine (type `dict`).

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
    repository = DeviceRepository(db)
    existing = await repository.get_by_ip_address(payload["ip_address"])
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="IP address already exists")
    return await repository.create_device(payload)


async def update_device(db: AsyncSession, device_id: int, payload: dict):
    """Update device for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        device_id: device id value used by this routine (type `int`).
        payload: payload value used by this routine (type `dict`).

    Returns:
        The computed result, response payload, or side-effect outcome for the caller.
    """
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
    """Delete device for business services that coordinate repositories and domain workflows. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        db: db value used by this routine (type `AsyncSession`).
        device_id: device id value used by this routine (type `int`).

    Returns:
        None. The routine is executed for its side effects.
    """
    repository = DeviceRepository(db)
    device = await repository.get_by_id(device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    await repository.delete_device(device)
