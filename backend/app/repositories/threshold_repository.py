from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from ..models.threshold import Threshold


class ThresholdRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_thresholds(self) -> list[Threshold]:
        query: Select[tuple[Threshold]] = select(Threshold).order_by(Threshold.key.asc())
        return list(self.db.scalars(query).all())

    def get_by_key(self, key: str) -> Threshold | None:
        query: Select[tuple[Threshold]] = select(Threshold).where(Threshold.key == key)
        return self.db.scalars(query).first()

    def upsert_threshold(self, key: str, value: float, description: str | None = None) -> Threshold:
        threshold = self.get_by_key(key)
        if threshold is None:
            threshold = Threshold(key=key, value=value, description=description)
            self.db.add(threshold)
        else:
            threshold.value = value
            threshold.description = description
        self.db.commit()
        self.db.refresh(threshold)
        return threshold
