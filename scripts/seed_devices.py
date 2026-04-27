"""Define module logic for `scripts/seed_devices.py`.

This module contains project-specific implementation details.
"""

SEED_DEVICES = [
    {"name": "Gateway Lokal", "ip_address": "192.168.1.1", "device_type": "internet_target"},
    {"name": "Google DNS", "ip_address": "8.8.8.8", "device_type": "internet_target"},
    {"name": "Cloudflare DNS", "ip_address": "1.1.1.1", "device_type": "internet_target"},
    {"name": "Mikrotik Utama", "ip_address": "192.168.1.254", "device_type": "mikrotik"},
    {"name": "Server Monitoring", "ip_address": "192.168.1.10", "device_type": "server"},
    {"name": "NVR Kantor", "ip_address": "192.168.1.20", "device_type": "nvr"},
    {"name": "Switch Lantai 1", "ip_address": "192.168.1.30", "device_type": "switch"},
    {"name": "AP Meeting Room", "ip_address": "192.168.1.40", "device_type": "access_point"},
    {"name": "Printer Finance", "ip_address": "192.168.1.50", "device_type": "printer"},
]


if __name__ == "__main__":
    import asyncio

    from backend.app.db.init_db import init_db
    from backend.app.db.session import SessionLocal
    from backend.app.repositories.device_repository import DeviceRepository

    async def main() -> None:
        await init_db()
        async with SessionLocal() as db:
            devices = await DeviceRepository(db).upsert_devices(SEED_DEVICES)
        print(f"Seeded {len(devices)} devices.")

    asyncio.run(main())
