SEED_THRESHOLDS = {
    "cpu_warning": 90,
    "ram_warning": 90,
    "disk_warning": 85,
    "packet_loss_warning": 20,
    "packet_loss_critical": 50,
    "jitter_warning": 30,
    "jitter_critical": 75,
    "dns_resolution_warning": 500,
    "http_response_warning": 1000,
}


if __name__ == "__main__":
    from backend.app.db.init_db import init_db
    from backend.app.db.session import SessionLocal
    from backend.app.services.threshold_service import DEFAULT_THRESHOLDS
    from backend.app.repositories.threshold_repository import ThresholdRepository

    init_db()
    with SessionLocal() as db:
        repository = ThresholdRepository(db)
        for key, value in SEED_THRESHOLDS.items():
            description = DEFAULT_THRESHOLDS.get(key, (value, None))[1]
            repository.upsert_threshold(key, float(value), description)
    print(f"Seeded {len(SEED_THRESHOLDS)} thresholds.")
