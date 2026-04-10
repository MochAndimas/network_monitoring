from sqlalchemy import Select, desc, select
from sqlalchemy.orm import Session

from ..models.alert import Alert


class AlertRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_active_alerts(self) -> list[Alert]:
        query: Select[tuple[Alert]] = (
            select(Alert).where(Alert.status == "active").order_by(desc(Alert.created_at), desc(Alert.id))
        )
        return list(self.db.scalars(query).all())

    def count_active_alerts(self) -> int:
        return len(self.list_active_alerts())

    def get_active_alert(self, device_id: int | None, alert_type: str) -> Alert | None:
        query: Select[tuple[Alert]] = select(Alert).where(
            Alert.status == "active",
            Alert.device_id == device_id,
            Alert.alert_type == alert_type,
        )
        return self.db.scalars(query).first()

    def create_alert(self, payload: dict) -> Alert:
        alert = Alert(**payload)
        self.db.add(alert)
        self.db.commit()
        self.db.refresh(alert)
        return alert

    def resolve_alert(self, alert: Alert, resolved_at) -> Alert:
        alert.status = "resolved"
        alert.resolved_at = resolved_at
        self.db.commit()
        self.db.refresh(alert)
        return alert
