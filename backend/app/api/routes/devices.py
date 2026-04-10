from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ...api.deps import require_internal_api_key
from ...api.schemas import DeviceCreate, DeviceListItem, DeviceTypeOption, DeviceUpdate
from ...core.constants import DEVICE_TYPE_CHOICES
from ...db.session import get_db
from ...services.device_service import create_device, get_device_row, list_device_rows, update_device

router = APIRouter()


@router.get("/meta/types", response_model=list[DeviceTypeOption])
async def list_device_types() -> list[DeviceTypeOption]:
    return [
        DeviceTypeOption(value=device_type, label=device_type.replace("_", " ").title())
        for device_type in DEVICE_TYPE_CHOICES
    ]


@router.get("", response_model=list[DeviceListItem])
async def list_devices(db: Session = Depends(get_db)) -> list[DeviceListItem]:
    return [DeviceListItem(**row) for row in list_device_rows(db)]


@router.get("/{device_id}", response_model=DeviceListItem)
async def get_device(device_id: int, db: Session = Depends(get_db)) -> DeviceListItem:
    return DeviceListItem(**get_device_row(db, device_id))


@router.post("", response_model=DeviceListItem, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_internal_api_key)])
async def create_device_endpoint(payload: DeviceCreate, db: Session = Depends(get_db)) -> DeviceListItem:
    created_device = create_device(db, payload.model_dump())
    return DeviceListItem(**get_device_row(db, created_device.id))


@router.put("/{device_id}", response_model=DeviceListItem, dependencies=[Depends(require_internal_api_key)])
async def update_device_endpoint(device_id: int, payload: DeviceUpdate, db: Session = Depends(get_db)) -> DeviceListItem:
    updated_device = update_device(db, device_id, payload.model_dump(exclude_unset=True))
    return DeviceListItem(**get_device_row(db, updated_device.id))
