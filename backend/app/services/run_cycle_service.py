from sqlalchemy.orm import Session

from ..alerting.engine import evaluate_alerts
from ..monitors.device.service import run_device_checks
from ..monitors.internet.service import run_internet_checks
from ..monitors.mikrotik.service import run_mikrotik_checks
from ..monitors.server.service import run_server_checks
from .monitoring_service import persist_metrics


def run_monitoring_cycle(db: Session) -> dict:
    metrics = []
    for runner in (run_internet_checks, run_device_checks, run_server_checks, run_mikrotik_checks):
        metrics.extend(runner(db))

    persisted = persist_metrics(db, metrics)
    alert_events = evaluate_alerts(db)

    return {
        "metrics_collected": len(persisted),
        "alerts_created": sum(1 for event in alert_events if event["action"] == "created"),
        "alerts_resolved": sum(1 for event in alert_events if event["action"] == "resolved"),
        "incidents_created": sum(1 for event in alert_events if event.get("incident_action") == "created"),
        "incidents_resolved": sum(1 for event in alert_events if event.get("incident_action") == "resolved"),
    }
