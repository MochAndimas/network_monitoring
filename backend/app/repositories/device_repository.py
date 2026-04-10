from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from ..models.device import Device


class DeviceRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_devices(self, active_only: bool = False) -> list[Device]:
        query: Select[tuple[Device]] = select(Device).order_by(Device.name.asc())
        if active_only:
            query = query.where(Device.is_active.is_(True))
        return list(self.db.scalars(query).all())

    def list_by_type(self, device_type: str, active_only: bool = True) -> list[Device]:
        query: Select[tuple[Device]] = select(Device).where(Device.device_type == device_type)
        if active_only:
            query = query.where(Device.is_active.is_(True))
        query = query.order_by(Device.name.asc())
        return list(self.db.scalars(query).all())

    def list_by_types(self, device_types: list[str], active_only: bool = True) -> list[Device]:
        query: Select[tuple[Device]] = select(Device).where(Device.device_type.in_(device_types))
        if active_only:
            query = query.where(Device.is_active.is_(True))
        query = query.order_by(Device.name.asc())
        return list(self.db.scalars(query).all())

    def get_by_id(self, device_id: int) -> Device | None:
        return self.db.get(Device, device_id)

    def get_by_ip_address(self, ip_address: str) -> Device | None:
        query: Select[tuple[Device]] = select(Device).where(Device.ip_address == ip_address)
        return self.db.scalars(query).first()

    def upsert_devices(self, payloads: list[dict]) -> list[Device]:
        existing = {
            device.ip_address: device
            for device in self.db.scalars(select(Device).where(Device.ip_address.in_([item["ip_address"] for item in payloads]))).all()
        }

        devices: list[Device] = []
        for payload in payloads:
            device = existing.get(payload["ip_address"])
            if device is None:
                device = Device(**payload)
                self.db.add(device)
            else:
                for field, value in payload.items():
                    setattr(device, field, value)
            devices.append(device)

        self.db.commit()
        for device in devices:
            self.db.refresh(device)
        return devices

    def create_device(self, payload: dict) -> Device:
        device = Device(**payload)
        self.db.add(device)
        self.db.commit()
        self.db.refresh(device)
        return device

    def update_device(self, device: Device, payload: dict) -> Device:
        for field, value in payload.items():
            setattr(device, field, value)
        self.db.commit()
        self.db.refresh(device)
        return device
