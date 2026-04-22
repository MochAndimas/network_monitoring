"""Provide FastAPI route handlers and HTTP helpers for the network monitoring project."""

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import require_write_access
from ...api.schemas import DeviceCreate, DeviceListItem, DeviceListPage, DeviceOption, DeviceTypeOption, PageMeta, DeviceUpdate
from ...core.constants import DEVICE_TYPE_CHOICES
from ...db.session import get_db
from ...repositories.device_repository import DeviceRepository
from ...services.audit_service import record_admin_audit_log
from ...services.device_service import (
    create_device,
    delete_device,
    get_device_row,
    list_device_rows_filtered,
    update_device,
)

router = APIRouter()


@router.get("/meta/types", response_model=list[DeviceTypeOption])
async def list_device_types() -> list[DeviceTypeOption]:
    """Return a list of device types for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Returns:
        `list[DeviceTypeOption]` result produced by the routine.
    """
    return [
        DeviceTypeOption(value=device_type, label=device_type.replace("_", " ").title())
        for device_type in DEVICE_TYPE_CHOICES
    ]


@router.get("/status-summary", response_model=dict[str, int])
async def get_device_status_summary(
    active_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Return device status summary for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        active_only: active only value used by this routine (type `bool`, optional).
        db: db value used by this routine (type `AsyncSession`, optional).

    Returns:
        `dict[str, int]` result produced by the routine.
    """
    return await DeviceRepository(db).summarize_device_status_counts(active_only=active_only)


@router.get("/options", response_model=list[DeviceOption])
async def list_device_options(
    active_only: bool = Query(default=False),
    search: str | None = Query(default=None, min_length=1, max_length=150),
    limit: int = Query(default=300, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[DeviceOption]:
    """Return a list of device options for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        active_only: active only value used by this routine (type `bool`, optional).
        search: search value used by this routine (type `str | None`, optional).
        limit: limit value used by this routine (type `int`, optional).
        offset: offset value used by this routine (type `int`, optional).
        db: db value used by this routine (type `AsyncSession`, optional).

    Returns:
        `list[DeviceOption]` result produced by the routine.
    """
    return [
        DeviceOption(**item)
        for item in await DeviceRepository(db).list_device_options(
            active_only=active_only,
            search=search,
            limit=limit,
            offset=offset,
        )
    ]


@router.get("", response_model=list[DeviceListItem])
async def list_devices(
    active_only: bool = Query(default=False),
    device_type: str | None = Query(default=None),
    latest_status: str | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1, max_length=150),
    limit: int | None = Query(default=None, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[DeviceListItem]:
    """Return a list of devices for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        active_only: active only value used by this routine (type `bool`, optional).
        device_type: device type value used by this routine (type `str | None`, optional).
        latest_status: latest status value used by this routine (type `str | None`, optional).
        search: search value used by this routine (type `str | None`, optional).
        limit: limit value used by this routine (type `int | None`, optional).
        offset: offset value used by this routine (type `int`, optional).
        db: db value used by this routine (type `AsyncSession`, optional).

    Returns:
        `list[DeviceListItem]` result produced by the routine.
    """
    rows = await list_device_rows_filtered(
        db,
        active_only=active_only,
        device_type=device_type,
        latest_status=latest_status,
        search=search,
        limit=limit,
        offset=offset,
    )
    return [DeviceListItem(**row) for row in rows]


@router.get("/paged", response_model=DeviceListPage)
async def list_devices_paged(
    active_only: bool = Query(default=False),
    device_type: str | None = Query(default=None),
    latest_status: str | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1, max_length=150),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> DeviceListPage:
    """Return a list of devices paged for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        active_only: active only value used by this routine (type `bool`, optional).
        device_type: device type value used by this routine (type `str | None`, optional).
        latest_status: latest status value used by this routine (type `str | None`, optional).
        search: search value used by this routine (type `str | None`, optional).
        limit: limit value used by this routine (type `int`, optional).
        offset: offset value used by this routine (type `int`, optional).
        db: db value used by this routine (type `AsyncSession`, optional).

    Returns:
        `DeviceListPage` result produced by the routine.
    """
    rows, total = await DeviceRepository(db).list_device_status_rows_paged(
        active_only=active_only,
        device_type=device_type,
        latest_status=latest_status,
        search=search,
        limit=limit,
        offset=offset,
    )
    return DeviceListPage(
        items=[DeviceListItem(**row) for row in rows],
        meta=PageMeta(total=total, limit=limit, offset=offset),
    )


@router.get("/{device_id}", response_model=DeviceListItem)
async def get_device(device_id: int, db: AsyncSession = Depends(get_db)) -> DeviceListItem:
    """Return device for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        device_id: device id value used by this routine (type `int`).
        db: db value used by this routine (type `AsyncSession`, optional).

    Returns:
        `DeviceListItem` result produced by the routine.
    """
    return DeviceListItem(**await get_device_row(db, device_id))


@router.post("", response_model=DeviceListItem, status_code=status.HTTP_201_CREATED)
async def create_device_endpoint(
    payload: DeviceCreate,
    request: Request,
    actor=Depends(require_write_access),
    db: AsyncSession = Depends(get_db),
) -> DeviceListItem:
    """Create device endpoint for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        payload: payload value used by this routine (type `DeviceCreate`).
        request: request value used by this routine (type `Request`).
        actor: actor value used by this routine (optional).
        db: db value used by this routine (type `AsyncSession`, optional).

    Returns:
        `DeviceListItem` result produced by the routine.
    """
    created_device = await create_device(db, payload.model_dump())
    await record_admin_audit_log(
        db,
        actor=actor,
        action="device.create",
        target_type="device",
        target_id=str(created_device.id),
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
        details=payload.model_dump(),
    )
    return DeviceListItem(**await get_device_row(db, created_device.id))


@router.put("/{device_id}", response_model=DeviceListItem)
async def update_device_endpoint(
    device_id: int,
    payload: DeviceUpdate,
    request: Request,
    actor=Depends(require_write_access),
    db: AsyncSession = Depends(get_db),
) -> DeviceListItem:
    """Update device endpoint for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        device_id: device id value used by this routine (type `int`).
        payload: payload value used by this routine (type `DeviceUpdate`).
        request: request value used by this routine (type `Request`).
        actor: actor value used by this routine (optional).
        db: db value used by this routine (type `AsyncSession`, optional).

    Returns:
        `DeviceListItem` result produced by the routine.
    """
    updated_device = await update_device(db, device_id, payload.model_dump(exclude_unset=True))
    await record_admin_audit_log(
        db,
        actor=actor,
        action="device.update",
        target_type="device",
        target_id=str(device_id),
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
        details=payload.model_dump(exclude_unset=True),
    )
    return DeviceListItem(**await get_device_row(db, updated_device.id))


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device_endpoint(
    device_id: int,
    request: Request,
    actor=Depends(require_write_access),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete device endpoint for FastAPI route handlers and HTTP helpers. This coroutine may perform asynchronous I/O or coordinate async dependencies.

    Args:
        device_id: device id value used by this routine (type `int`).
        request: request value used by this routine (type `Request`).
        actor: actor value used by this routine (optional).
        db: db value used by this routine (type `AsyncSession`, optional).

    Returns:
        None. The routine is executed for its side effects.
    """
    existing = await get_device_row(db, device_id)
    await delete_device(db, device_id)
    await record_admin_audit_log(
        db,
        actor=actor,
        action="device.delete",
        target_type="device",
        target_id=str(device_id),
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
        details={
            "name": existing["name"],
            "ip_address": existing["ip_address"],
            "device_type": existing["device_type"],
        },
    )
