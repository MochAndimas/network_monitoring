from backend.app.db.init_db import init_db
from backend.app.db.session import SessionLocal
from backend.app.services.run_cycle_service import run_monitoring_cycle


if __name__ == "__main__":
    init_db()
    with SessionLocal() as db:
        result = run_monitoring_cycle(db)
    print("Monitoring cycle completed.")
    for key, value in result.items():
        print(f"- {key}: {value}")
