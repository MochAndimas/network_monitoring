from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import require_internal_api_key
from ...api.schemas import DeviceCreate, DeviceListItem, DeviceListPage, DeviceTypeOption, PageMeta, DeviceUpdate
from ...core.constants import DEVICE_TYPE_CHOICES
from ...db.session import get_db
from ...services.device_service import (
    count_device_rows_filtered,
    create_device,
    get_device_row,
    list_device_rows_filtered,
    update_device,
)

router = APIRouter()


@router.get("/meta/types", response_model=list[DeviceTypeOption])
async def list_device_types() -> list[DeviceTypeOption]:
    return [
        DeviceTypeOption(value=device_type, label=device_type.replace("_", " ").title())
        for device_type in DEVICE_TYPE_CHOICES
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
    rows = await list_device_rows_filtered(
        db,
        active_only=active_only,
        device_type=device_type,
        latest_status=latest_status,
        search=search,
        limit=limit,
        offset=offset,
    )
    total = await count_device_rows_filtered(
        db,
        active_only=active_only,
        device_type=device_type,
        latest_status=latest_status,
        search=search,
    )
    return DeviceListPage(
        items=[DeviceListItem(**row) for row in rows],
        meta=PageMeta(total=total, limit=limit, offset=offset),
    )


@router.get("/{device_id}", response_model=DeviceListItem)
async def get_device(device_id: int, db: AsyncSession = Depends(get_db)) -> DeviceListItem:
    return DeviceListItem(**await get_device_row(db, device_id))


@router.post("", response_model=DeviceListItem, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_internal_api_key)])
async def create_device_endpoint(payload: DeviceCreate, db: AsyncSession = Depends(get_db)) -> DeviceListItem:
    created_device = await create_device(db, payload.model_dump())
    return DeviceListItem(**await get_device_row(db, created_device.id))


@router.put("/{device_id}", response_model=DeviceListItem, dependencies=[Depends(require_internal_api_key)])
async def update_device_endpoint(device_id: int, payload: DeviceUpdate, db: AsyncSession = Depends(get_db)) -> DeviceListItem:
    updated_device = await update_device(db, device_id, payload.model_dump(exclude_unset=True))
    return DeviceListItem(**await get_device_row(db, updated_device.id))
