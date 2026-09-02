"""Database query helpers for incident repository data."""

from datetime import timedelta
import json

from sqlalchemy import Select, case, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.time import utcnow
from ..models.alert import Alert
from ..models.device import Device
from ..models.incident import Incident, IncidentTimelineEvent


SEVERITY_PRIORITY = {
    "critical": 4,
    "high": 3,
    "warning": 2,
    "info": 1,
}


def _severity_priority_expression(value):
    """Build a portable SQL severity rank expression (higher is more urgent)."""
    return case(
        (func.lower(value) == "critical", 4),
        (func.lower(value) == "high", 3),
        (func.lower(value) == "warning", 2),
        (func.lower(value) == "info", 1),
        else_=0,
    )


def _effective_severity_priority_expression():
    """Resolve override-or-related-alert severity inside SQL for paged filtering."""
    related_alert_priority = (
        select(func.max(_severity_priority_expression(Alert.severity)))
        .where(Alert.device_id == Incident.device_id)
        .where(Alert.created_at >= Incident.started_at)
        .where(or_(Incident.ended_at.is_(None), Alert.created_at <= Incident.ended_at))
        .correlate(Incident)
        .scalar_subquery()
    )
    override_priority = _severity_priority_expression(Incident.severity_override)
    return case((override_priority > 0, override_priority), else_=func.coalesce(related_alert_priority, 0))


class IncidentNotFoundError(ValueError):
    """Raised when an incident lookup cannot find a matching record."""


class IncidentRepository:
    """Database access object for Incident records."""
    def __init__(self, db: AsyncSession):
        """Initialize the object with its runtime dependencies."""
        self.db = db

    async def list_active_incidents(self) -> list[Incident]:
        """Query active incidents from the database."""
        query: Select[tuple[Incident]] = (
            select(Incident).where(Incident.status == "active").order_by(desc(Incident.started_at), desc(Incident.id))
        )
        return list((await self.db.scalars(query)).all())

    async def list_active_incidents_by_device_ids(self, device_ids: set[int | None]) -> list[Incident]:
        """Return active incidents for devices currently under alert evaluation."""
        if not device_ids:
            return []
        concrete_device_ids = {device_id for device_id in device_ids if device_id is not None}
        conditions = []
        if concrete_device_ids:
            conditions.append(Incident.device_id.in_(concrete_device_ids))
        if None in device_ids:
            conditions.append(Incident.device_id.is_(None))
        if not conditions:
            return []
        query: Select[tuple[Incident]] = (
            select(Incident)
            .where(Incident.status == "active")
            .where(or_(*conditions))
            .order_by(desc(Incident.started_at), desc(Incident.id))
        )
        return list((await self.db.scalars(query)).all())

    async def count_active_incidents(self) -> int:
        """Query active incidents from the database."""
        query = select(func.count()).select_from(Incident).where(Incident.status == "active")
        return int(await self.db.scalar(query) or 0)

    async def list_incident_rows(
        self,
        status: str | None = None,
        *,
        limit: int = 100,
        offset: int = 0,
        search: str | None = None,
        site: str | None = None,
        device_id: int | None = None,
        severity: str | None = None,
        sort: str = "newest",
    ) -> list[dict]:
        """Query incident rows from the database."""
        query = select(Incident, Device.name, Device.site).outerjoin(Device, Device.id == Incident.device_id)
        if status:
            query = query.where(Incident.status == status)
        if device_id is not None:
            query = query.where(Incident.device_id == device_id)
        normalized_site = str(site or "").strip().lower()
        if normalized_site:
            query = query.where(func.lower(Device.site) == normalized_site)
        normalized_search = str(search or "").strip().lower()
        if normalized_search:
            query = query.where(
                or_(
                    func.lower(Incident.summary).like(f"%{normalized_search}%"),
                    func.lower(Device.name).like(f"%{normalized_search}%"),
                )
            )
        effective_severity = _effective_severity_priority_expression()
        requested_severity = SEVERITY_PRIORITY.get(str(severity or "").strip().lower())
        if requested_severity is not None:
            query = query.where(effective_severity == requested_severity)
        if sort == "severity":
            query = query.order_by(desc(effective_severity), desc(Incident.started_at), desc(Incident.id))
        else:
            query = query.order_by(desc(Incident.started_at), desc(Incident.id))
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        rows = (await self.db.execute(query)).all()
        incident_summaries = await self._incident_alert_summaries([incident for incident, _device_name, _site in rows])
        severities = await self._incident_effective_severities([incident for incident, _device_name, _site in rows])
        return [
            {
                "id": incident.id,
                "device_id": incident.device_id,
                "device_name": device_name,
                "site": site_name,
                "status": incident.status,
                "summary": incident_summaries.get(incident.id, incident.summary),
                "owner": incident.owner,
                "assignee": incident.assignee,
                "severity_override": incident.severity_override,
                "effective_severity": severities.get(incident.id),
                "note": incident.note,
                "acknowledged_at": incident.acknowledged_at,
                "acknowledged_by": incident.acknowledged_by,
                "started_at": incident.started_at,
                "ended_at": incident.ended_at,
                "resolved_by": incident.resolved_by,
                "updated_at": incident.updated_at,
            }
            for incident, device_name, site_name in rows
        ]

    async def list_incident_rows_paged(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        search: str | None = None,
        site: str | None = None,
        device_id: int | None = None,
        severity: str | None = None,
        sort: str = "newest",
    ) -> tuple[list[dict], int]:
        """Query incident rows paged from the database."""
        rows = await self.list_incident_rows(status=status, limit=limit, offset=offset, search=search, site=site, device_id=device_id, severity=severity, sort=sort)
        if offset == 0 and len(rows) < limit:
            return rows, len(rows)
        return rows, await self.count_incident_rows(status=status, search=search, site=site, device_id=device_id, severity=severity)

    async def get_incident_row(self, incident_id: int) -> dict:
        """Return one incident row with derived summary and severity."""
        query = select(Incident, Device.name, Device.site).outerjoin(Device, Device.id == Incident.device_id).where(Incident.id == incident_id)
        row = (await self.db.execute(query)).first()
        if row is None:
            raise IncidentNotFoundError(f"Incident {incident_id} not found")
        incident, device_name, site_name = row
        summaries = await self._incident_alert_summaries([incident])
        severities = await self._incident_effective_severities([incident])
        return {
            "id": incident.id,
            "device_id": incident.device_id,
            "device_name": device_name,
            "site": site_name,
            "status": incident.status,
            "summary": summaries.get(incident.id, incident.summary),
            "owner": incident.owner,
            "assignee": incident.assignee,
            "severity_override": incident.severity_override,
            "effective_severity": severities.get(incident.id),
            "note": incident.note,
            "acknowledged_at": incident.acknowledged_at,
            "acknowledged_by": incident.acknowledged_by,
            "started_at": incident.started_at,
            "ended_at": incident.ended_at,
            "resolved_by": incident.resolved_by,
            "updated_at": incident.updated_at,
        }

    async def count_incident_rows(self, *, status: str | None = None, search: str | None = None, site: str | None = None, device_id: int | None = None, severity: str | None = None) -> int:
        """Query incident rows from the database."""
        query = select(func.count()).select_from(Incident)
        if status:
            query = query.where(Incident.status == status)
        if device_id is not None:
            query = query.where(Incident.device_id == device_id)
        normalized_site = str(site or "").strip().lower()
        if normalized_site:
            query = query.join(Device, Device.id == Incident.device_id, isouter=True).where(func.lower(Device.site) == normalized_site)
        normalized_search = str(search or "").strip().lower()
        if normalized_search:
            if not normalized_site:
                query = query.join(Device, Device.id == Incident.device_id, isouter=True)
            query = query.where(
                or_(
                    func.lower(Incident.summary).like(f"%{normalized_search}%"),
                    func.lower(Device.name).like(f"%{normalized_search}%"),
                )
            )
        requested_severity = SEVERITY_PRIORITY.get(str(severity or "").strip().lower())
        if requested_severity is not None:
            query = query.where(_effective_severity_priority_expression() == requested_severity)
        return int(await self.db.scalar(query) or 0)

    async def _incident_alert_summaries(self, incidents: list[Incident]) -> dict[int, str]:
        """Build richer incident summaries from alerts inside each incident window."""
        incident_windows = [
            incident
            for incident in incidents
            if incident.id is not None and incident.device_id is not None and incident.started_at is not None
        ]
        if not incident_windows:
            return {}

        now = utcnow()
        device_ids = {incident.device_id for incident in incident_windows if incident.device_id is not None}
        min_started_at = min(incident.started_at for incident in incident_windows)
        max_ended_at = max((incident.ended_at or now) for incident in incident_windows)
        alert_rows = list(
            (
                await self.db.scalars(
                    select(Alert)
                    .where(Alert.device_id.in_(device_ids))
                    .where(Alert.created_at >= min_started_at)
                    .where(Alert.created_at <= max_ended_at)
                    .order_by(Alert.created_at.asc(), Alert.id.asc())
                )
            ).all()
        )

        summaries: dict[int, str] = {}
        for incident in incident_windows:
            incident_ended_at = incident.ended_at or now
            incident_alerts = [
                alert
                for alert in alert_rows
                if alert.device_id == incident.device_id
                and alert.created_at >= incident.started_at
                and alert.created_at <= incident_ended_at
            ]
            if incident_alerts:
                summaries[incident.id] = _format_incident_alert_summary(incident_alerts)
        return summaries

    async def create_incident(self, payload: dict, *, commit: bool = True) -> Incident:
        """Persist incident changes in the database."""
        payload.setdefault("updated_at", utcnow())
        incident = Incident(**payload)
        self.db.add(incident)
        await self.db.flush()
        await self.add_timeline_event(
            incident,
            event_type="created",
            actor="system",
            message=incident.summary,
            metadata={"device_id": incident.device_id},
            commit=False,
        )
        if commit:
            await self.db.commit()
            await self.db.refresh(incident)
        return incident

    async def resolve_incident(
        self,
        incident: Incident,
        ended_at,
        *,
        actor: str | None = "system",
        note: str | None = None,
        commit: bool = True,
    ) -> Incident:
        """Persist incident changes in the database."""
        incident.status = "resolved"
        incident.ended_at = ended_at
        incident.resolved_by = actor
        incident.updated_at = ended_at
        if note:
            incident.note = _merge_note(incident.note, note)
        await self.db.flush()
        await self.add_timeline_event(
            incident,
            event_type="resolved",
            actor=actor,
            message=note or "Incident resolved",
            commit=False,
        )
        if commit:
            await self.db.commit()
            await self.db.refresh(incident)
        return incident

    async def get_incident(self, incident_id: int) -> Incident:
        """Return one incident or raise a domain error."""
        incident = await self.db.get(Incident, incident_id)
        if incident is None:
            raise IncidentNotFoundError(f"Incident {incident_id} not found")
        return incident

    async def acknowledge_incident(
        self,
        incident_id: int,
        *,
        actor: str,
        note: str | None = None,
        assignee: str | None = None,
        commit: bool = True,
    ) -> Incident:
        """Acknowledge an active incident and append a timeline event."""
        incident = await self.get_incident(incident_id)
        acknowledged_at = utcnow()
        if assignee is not None:
            incident.assignee = _clean_optional(assignee)
        if note:
            incident.note = _merge_note(incident.note, note)
        if incident.acknowledged_at is None:
            incident.acknowledged_at = acknowledged_at
            incident.acknowledged_by = actor
        incident.updated_at = acknowledged_at
        await self.db.flush()
        await self.add_timeline_event(
            incident,
            event_type="acknowledged",
            actor=actor,
            message=note or "Incident acknowledged",
            metadata={"assignee": incident.assignee},
            commit=False,
        )
        if commit:
            await self.db.commit()
            await self.db.refresh(incident)
        return incident

    async def update_incident_workflow(
        self,
        incident_id: int,
        *,
        actor: str,
        owner: str | None = None,
        assignee: str | None = None,
        severity_override: str | None = None,
        note: str | None = None,
        commit: bool = True,
    ) -> Incident:
        """Update mutable workflow metadata for an incident."""
        incident = await self.get_incident(incident_id)
        incident.owner = _clean_optional(owner)
        incident.assignee = _clean_optional(assignee)
        incident.severity_override = _normalize_severity(severity_override)
        incident.note = _clean_optional(note)
        incident.updated_at = utcnow()
        await self.db.flush()
        await self.add_timeline_event(
            incident,
            event_type="updated",
            actor=actor,
            message="Incident workflow fields updated",
            metadata={
                "owner": incident.owner,
                "assignee": incident.assignee,
                "severity_override": incident.severity_override,
            },
            commit=False,
        )
        if commit:
            await self.db.commit()
            await self.db.refresh(incident)
        return incident

    async def manually_resolve_incident(
        self,
        incident_id: int,
        *,
        actor: str,
        note: str | None = None,
        commit: bool = True,
    ) -> Incident:
        """Resolve an incident from an operator action."""
        incident = await self.get_incident(incident_id)
        return await self.resolve_incident(incident, utcnow(), actor=actor, note=note, commit=commit)

    async def reopen_incident(
        self,
        incident_id: int,
        *,
        actor: str,
        note: str | None = None,
        commit: bool = True,
    ) -> Incident:
        """Reopen a resolved incident from an operator action."""
        incident = await self.get_incident(incident_id)
        reopened_at = utcnow()
        incident.status = "active"
        incident.ended_at = None
        incident.resolved_by = None
        incident.updated_at = reopened_at
        if note:
            incident.note = _merge_note(incident.note, note)
        await self.db.flush()
        await self.add_timeline_event(
            incident,
            event_type="reopened",
            actor=actor,
            message=note or "Incident reopened",
            commit=False,
        )
        if commit:
            await self.db.commit()
            await self.db.refresh(incident)
        return incident

    async def list_timeline_rows(self, incident_id: int) -> list[dict]:
        """Return timeline rows for one incident."""
        await self.get_incident(incident_id)
        query = (
            select(IncidentTimelineEvent)
            .where(IncidentTimelineEvent.incident_id == incident_id)
            .order_by(IncidentTimelineEvent.created_at.asc(), IncidentTimelineEvent.id.asc())
        )
        rows = list((await self.db.scalars(query)).all())
        return [
            {
                "id": row.id,
                "incident_id": row.incident_id,
                "event_type": row.event_type,
                "actor": row.actor,
                "message": row.message,
                "metadata": _decode_metadata(row.event_metadata),
                "created_at": row.created_at,
            }
            for row in rows
        ]

    async def add_timeline_event(
        self,
        incident: Incident,
        *,
        event_type: str,
        message: str,
        actor: str | None = None,
        metadata: dict | None = None,
        commit: bool = True,
    ) -> IncidentTimelineEvent:
        """Append one event to an incident timeline."""
        event = IncidentTimelineEvent(
            incident_id=incident.id,
            event_type=event_type,
            actor=actor,
            message=message[:500],
            event_metadata=json.dumps(metadata or {}, sort_keys=True) if metadata else None,
            created_at=utcnow(),
        )
        self.db.add(event)
        incident.updated_at = utcnow()
        await self.db.flush()
        if commit:
            await self.db.commit()
            await self.db.refresh(event)
        return event

    async def add_alert_timeline_event(
        self,
        *,
        device_id: int | None,
        alert_type: str | None,
        message: str,
        action: str,
        event_at,
        commit: bool = True,
    ) -> None:
        """Attach an alert state change to active incidents for the device."""
        incidents = await self._matching_incidents_for_event(device_id=device_id, event_at=event_at)
        for incident in incidents:
            await self.add_timeline_event(
                incident,
                event_type="alert_changed",
                actor="system",
                message=message,
                metadata={"action": action, "alert_type": alert_type, "device_id": device_id},
                commit=False,
            )
        if commit and incidents:
            await self.db.commit()

    async def add_notification_timeline_event_for_alert(
        self,
        *,
        alert: Alert,
        action: str,
        channel: str,
        notified_at,
        commit: bool = True,
    ) -> None:
        """Attach a successful notification send to the related incident timeline."""
        event_at = alert.resolved_at or notified_at
        incidents = await self._matching_incidents_for_event(device_id=alert.device_id, event_at=event_at)
        for incident in incidents:
            await self.add_timeline_event(
                incident,
                event_type="notification_sent",
                actor="system",
                message=f"{channel} notification sent for {action} {alert.alert_type}",
                metadata={"channel": channel, "action": action, "alert_id": alert.id, "alert_type": alert.alert_type},
                commit=False,
            )
        if commit and incidents:
            await self.db.commit()

    async def list_escalation_rows(
        self,
        *,
        critical_after_minutes: int = 15,
        high_after_minutes: int = 60,
        limit: int = 100,
    ) -> list[dict]:
        """Return active unacknowledged incidents that exceeded escalation windows."""
        current_time = utcnow()
        rows = await self.list_incident_rows(status="active", limit=limit, offset=0)
        escalation_rows: list[dict] = []
        for row in rows:
            if row.get("acknowledged_at") is not None:
                continue
            severity = str(row.get("effective_severity") or "").lower()
            threshold = critical_after_minutes if severity == "critical" else high_after_minutes if severity == "high" else None
            if threshold is None:
                continue
            started_at = row.get("started_at")
            if started_at is None or started_at > current_time - timedelta(minutes=threshold):
                continue
            row = dict(row)
            row["escalation_reason"] = f"{severity} incident unacknowledged for >= {threshold} minutes"
            row["escalation_after_minutes"] = threshold
            escalation_rows.append(row)
        return escalation_rows

    async def _incident_effective_severities(self, incidents: list[Incident]) -> dict[int, str | None]:
        """Resolve each incident severity from override or related alerts."""
        result: dict[int, str | None] = {
            incident.id: _normalize_severity(incident.severity_override)
            for incident in incidents
            if incident.id is not None and incident.severity_override
        }
        candidates = [
            incident
            for incident in incidents
            if incident.id is not None and incident.id not in result and incident.device_id is not None
        ]
        if not candidates:
            return result
        now = utcnow()
        device_ids = {incident.device_id for incident in candidates if incident.device_id is not None}
        min_started_at = min(incident.started_at for incident in candidates)
        max_ended_at = max((incident.ended_at or now) for incident in candidates)
        alerts = list(
            (
                await self.db.scalars(
                    select(Alert)
                    .where(Alert.device_id.in_(device_ids))
                    .where(Alert.created_at >= min_started_at)
                    .where(Alert.created_at <= max_ended_at)
                )
            ).all()
        )
        for incident in candidates:
            incident_ended_at = incident.ended_at or now
            incident_alerts = [
                alert
                for alert in alerts
                if alert.device_id == incident.device_id
                and alert.created_at >= incident.started_at
                and alert.created_at <= incident_ended_at
            ]
            result[incident.id] = _highest_severity(alert.severity for alert in incident_alerts)
        return result

    async def _matching_incidents_for_event(self, *, device_id: int | None, event_at) -> list[Incident]:
        """Find active or recently resolved incidents that match one alert/notification event."""
        if device_id is None:
            device_condition = Incident.device_id.is_(None)
        else:
            device_condition = Incident.device_id == device_id
        query = (
            select(Incident)
            .where(device_condition)
            .where(Incident.started_at <= event_at)
            .where(or_(Incident.ended_at.is_(None), Incident.ended_at >= event_at))
            .order_by(desc(Incident.started_at), desc(Incident.id))
        )
        return list((await self.db.scalars(query)).all())


def _format_incident_alert_summary(alerts: list[Alert]) -> str:
    """Format alert rows into a concise incident summary."""
    latest_alert_by_type: dict[str, Alert] = {}
    for alert in alerts:
        latest_alert_by_type[alert.alert_type] = alert

    ordered_alerts = sorted(latest_alert_by_type.values(), key=lambda item: (item.created_at, item.alert_type))
    alert_parts = [f"{alert.alert_type}: {alert.message}" for alert in ordered_alerts[:5]]
    extra_count = max(len(ordered_alerts) - len(alert_parts), 0)
    suffix = f"; +{extra_count} alert lain" if extra_count else ""
    return f"{len(ordered_alerts)} alert: " + "; ".join(alert_parts) + suffix


def _clean_optional(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_severity(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in SEVERITY_PRIORITY else None


def _highest_severity(values) -> str | None:
    severities = [_normalize_severity(value) for value in values]
    severities = [value for value in severities if value]
    if not severities:
        return None
    return max(severities, key=lambda item: SEVERITY_PRIORITY.get(item, 0))


def _merge_note(existing: str | None, note: str) -> str:
    clean_note = str(note or "").strip()
    if not clean_note:
        return existing or ""
    if not existing:
        return clean_note
    return f"{existing}\n\n{clean_note}"


def _decode_metadata(raw_value: str | None) -> dict:
    if not raw_value:
        return {}
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
