from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..repositories.device_repository import DeviceRepository
from .monitoring_service import build_device_status_rows


def list_device_rows(db: Session) -> list[dict]:
    return build_device_status_rows(db)


def get_device_row(db: Session, device_id: int) -> dict:
    rows = {row["id"]: row for row in build_device_status_rows(db)}
    if device_id not in rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return rows[device_id]


def create_device(db: Session, payload: dict):
    repository = DeviceRepository(db)
    existing = repository.get_by_ip_address(payload["ip_address"])
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="IP address already exists")
    return repository.create_device(payload)


def update_device(db: Session, device_id: int, payload: dict):
    repository = DeviceRepository(db)
    device = repository.get_by_id(device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    ip_address = payload.get("ip_address")
    if ip_address:
        existing = repository.get_by_ip_address(ip_address)
        if existing is not None and existing.id != device_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="IP address already exists")

    return repository.update_device(device, payload)
