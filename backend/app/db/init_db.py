from .base import Base
from .session import engine
from ..models import alert, device, incident, metric, metric_daily_rollup, threshold  # noqa: F401


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()
    print("Database tables created.")
