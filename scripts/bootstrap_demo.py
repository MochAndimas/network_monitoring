from backend.app.db.init_db import init_db
from backend.app.db.session import SessionLocal
from backend.app.repositories.device_repository import DeviceRepository
from backend.app.services.run_cycle_service import run_monitoring_cycle
from backend.app.services.threshold_service import ensure_default_thresholds
from scripts.seed_devices import SEED_DEVICES


if __name__ == "__main__":
    init_db()
    with SessionLocal() as db:
        devices = DeviceRepository(db).upsert_devices(SEED_DEVICES)
        ensure_default_thresholds(db)
        result = run_monitoring_cycle(db)

    print(f"Bootstrapped {len(devices)} devices and executed one monitoring cycle.")
    for key, value in result.items():
        print(f"- {key}: {value}")
