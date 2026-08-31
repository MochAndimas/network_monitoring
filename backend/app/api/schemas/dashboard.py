"""Pydantic schemas for dashboard payloads."""

from datetime import date, datetime
from ipaddress import ip_address

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...core.constants import DEVICE_TYPE_CHOICES


class DashboardSummary(BaseModel):
    """Pydantic schema for DashboardSummary payloads."""
    internet_status: str
    mikrotik_status: str
    server_status: str
    active_alerts: int


class DeviceListItem(BaseModel):
    """Pydantic schema for DeviceListItem payloads."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    ip_address: str
    device_type: str
    site: str | None = None
    location: str | None = None
    description: str | None = None
    is_active: bool
    latest_status: str = "unknown"
    latest_checked_at: datetime | None = None


class PageMeta(BaseModel):
    """Pydantic schema for PageMeta payloads."""
    total: int
    limit: int
    offset: int


class CursorPageMeta(BaseModel):
    """Pydantic schema for cursor-capable page metadata."""
    total: int | None
    limit: int
    offset: int
    next_cursor: str | None = None
    has_more: bool = False


class DeviceListPage(BaseModel):
    """Pydantic schema for DeviceListPage payloads."""
    items: list["DeviceListItem"]
    meta: CursorPageMeta


class DeviceCreate(BaseModel):
    """Pydantic schema for DeviceCreate payloads."""
    name: str = Field(min_length=1, max_length=150)
    ip_address: str = Field(min_length=1, max_length=50)
    device_type: str = Field(min_length=1, max_length=50)
    site: str = Field(min_length=1, max_length=100)
    location: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    is_active: bool = True

    @field_validator("ip_address")
    @classmethod
    def validate_ip_address(cls, value: str) -> str:
        """Validate ip address for API schemas."""
        ip_address(value)
        return value

    @field_validator("device_type")
    @classmethod
    def validate_device_type(cls, value: str) -> str:
        """Validate device type for API schemas."""
        if value not in DEVICE_TYPE_CHOICES:
            raise ValueError(f"device_type must be one of: {', '.join(DEVICE_TYPE_CHOICES)}")
        return value

    @field_validator("site")
    @classmethod
    def normalize_required_site(cls, value: str) -> str:
        """Require a meaningful site value instead of accepting whitespace."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("site must not be blank")
        return normalized


class DeviceUpdate(BaseModel):
    """Pydantic schema for DeviceUpdate payloads."""
    name: str | None = Field(default=None, min_length=1, max_length=150)
    ip_address: str | None = Field(default=None, min_length=1, max_length=50)
    device_type: str | None = Field(default=None, min_length=1, max_length=50)
    site: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None

    @field_validator("ip_address")
    @classmethod
    def validate_optional_ip_address(cls, value: str | None) -> str | None:
        """Validate optional ip address for API schemas."""
        if value is None:
            return value
        ip_address(value)
        return value

    @field_validator("device_type")
    @classmethod
    def validate_optional_device_type(cls, value: str | None) -> str | None:
        """Validate optional device type for API schemas."""
        if value is None:
            return value
        if value not in DEVICE_TYPE_CHOICES:
            raise ValueError(f"device_type must be one of: {', '.join(DEVICE_TYPE_CHOICES)}")
        return value

    @field_validator("site")
    @classmethod
    def normalize_optional_site(cls, value: str | None) -> str | None:
        """Allow omitting site on a patch, but never clearing it to whitespace."""
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("site must not be blank")
        return normalized


class MetricHistoryItem(BaseModel):
    """Pydantic schema for MetricHistoryItem payloads."""
    id: int
    device_id: int
    device_name: str
    metric_name: str
    metric_value: str
    metric_value_numeric: float | None = None
    status: str | None = None
    unit: str | None = None
    checked_at: datetime


class MetricHistoryPage(BaseModel):
    """Pydantic schema for MetricHistoryPage payloads."""
    items: list["MetricHistoryItem"]
    meta: CursorPageMeta


class MetricHistoryCursorPage(BaseModel):
    """Pydantic schema for cursor-capable MetricHistoryItem pages."""
    items: list["MetricHistoryItem"]
    meta: CursorPageMeta


class MetricPayloadMeta(BaseModel):
    """Pydantic schema for sampled metric payload metadata."""
    total: int
    limit: int
    offset: int
    sampled: bool | None = None


class MetricHistorySection(BaseModel):
    """Pydantic schema for a metric history section inside composite payloads."""
    items: list["MetricHistoryItem"]
    meta: MetricPayloadMeta


class MetricHistoryContextPayload(BaseModel):
    """Pydantic schema for composite metric history dashboard payloads."""
    metric_names: list[str]
    history: MetricHistorySection
    selected_device_history: MetricHistorySection
    selected_device_trend: MetricHistorySection
    latest_snapshot: MetricHistorySection
    selected_device_snapshot: MetricHistorySection
    latest_snapshot_status_summary: dict[str, int]
    snapshot_uptime_map: dict[str, str]


class MetricDailySummaryItem(BaseModel):
    """Pydantic schema for MetricDailySummaryItem payloads."""
    id: int
    device_id: int
    device_name: str
    device_type: str | None = None
    site: str | None = None
    rollup_date: date
    total_samples: int
    ping_samples: int
    down_count: int
    uptime_percentage: float | None = None
    average_ping_ms: float | None = None
    min_ping_ms: float | None = None
    max_ping_ms: float | None = None
    average_packet_loss_percent: float | None = None
    average_jitter_ms: float | None = None
    max_jitter_ms: float | None = None
    updated_at: datetime


class MetricDailySummaryPage(BaseModel):
    """Pydantic schema for MetricDailySummaryPage payloads."""
    items: list["MetricDailySummaryItem"]
    meta: PageMeta


class MetricSiteTypeTrendItem(BaseModel):
    """Long-term trend row grouped by site and device type."""

    summary_date: date
    site: str
    device_type: str
    device_count: int
    total_samples: int
    ping_samples: int
    down_count: int
    average_uptime_percentage: float | None = None
    average_ping_ms: float | None = None
    average_packet_loss_percent: float | None = None
    average_jitter_ms: float | None = None
    max_jitter_ms: float | None = None


class MetricColdArchiveItem(BaseModel):
    """Cold archive explorer row."""

    id: int
    device_id: int
    device_name: str
    device_type: str | None = None
    site: str | None = None
    archive_date: date
    archive_month: date
    metric_name: str
    status: str
    unit: str
    sample_count: int
    numeric_sample_count: int
    min_numeric_value: float | None = None
    max_numeric_value: float | None = None
    avg_numeric_value: float | None = None
    first_checked_at: datetime
    last_checked_at: datetime
    last_metric_value: str


class MetricColdArchivePage(BaseModel):
    """Cold archive paged response."""

    items: list["MetricColdArchiveItem"]
    meta: PageMeta


class MetricLongTermExplorerPayload(BaseModel):
    """Combined long-term explorer payload."""

    trends: list["MetricSiteTypeTrendItem"]
    archives: MetricColdArchivePage


class MetricFreshnessItem(BaseModel):
    """Pydantic schema for collector/site freshness summary rows."""
    collector: str
    site: str
    total_devices: int
    devices_with_data: int
    fresh_devices: int
    stale_devices: int
    no_data_devices: int
    freshness_status: str
    latest_checked_at: datetime | None = None
    oldest_checked_at: datetime | None = None


class MetricFreshnessSummary(BaseModel):
    """Pydantic schema for metric freshness summary payloads."""
    generated_at: datetime
    stale_after_minutes: int
    active_only: bool
    items: list["MetricFreshnessItem"]


class AlertItem(BaseModel):
    """Pydantic schema for AlertItem payloads."""
    id: int
    device_id: int | None = None
    device_name: str | None = None
    site: str | None = None
    alert_type: str
    severity: str
    message: str
    status: str
    created_at: datetime
    resolved_at: datetime | None = None


class AlertPage(BaseModel):
    """Pydantic schema for AlertPage payloads."""
    items: list["AlertItem"]
    meta: PageMeta


class IncidentItem(BaseModel):
    """Pydantic schema for IncidentItem payloads."""
    id: int
    device_id: int | None = None
    device_name: str | None = None
    site: str | None = None
    status: str
    summary: str
    owner: str | None = None
    assignee: str | None = None
    severity_override: str | None = None
    effective_severity: str | None = None
    note: str | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    resolved_by: str | None = None
    updated_at: datetime | None = None


class IncidentPage(BaseModel):
    """Pydantic schema for IncidentPage payloads."""
    items: list["IncidentItem"]
    meta: PageMeta


class IncidentWorkflowUpdate(BaseModel):
    """Request payload for mutable incident workflow fields."""

    owner: str | None = None
    assignee: str | None = None
    severity_override: str | None = None
    note: str | None = None


class IncidentActionRequest(BaseModel):
    """Request payload for incident workflow actions."""

    note: str | None = None
    assignee: str | None = None


class IncidentTimelineItem(BaseModel):
    """Pydantic schema for incident timeline payloads."""

    id: int
    incident_id: int
    event_type: str
    actor: str | None = None
    message: str
    metadata: dict
    created_at: datetime


class IncidentTimelineResponse(BaseModel):
    """Pydantic schema for one incident timeline response."""

    items: list["IncidentTimelineItem"]


class IncidentEscalationResponse(BaseModel):
    """Pydantic schema for incident escalation list."""

    items: list["IncidentItem"]


class RunCycleResult(BaseModel):
    """Pydantic schema for RunCycleResult payloads."""
    metrics_collected: int
    alerts_created: int
    alerts_resolved: int
    incidents_created: int
    incidents_resolved: int


class PerformanceBudgetItem(BaseModel):
    """Dashboard/API endpoint performance budget."""

    endpoint: str
    max_p95_ms: float
    max_payload_rows: int | None = None
    notes: str | None = None


class PerformanceBudgetResponse(BaseModel):
    """Performance budgets for dashboard/API endpoints."""

    items: list["PerformanceBudgetItem"]


class ThresholdItem(BaseModel):
    """Pydantic schema for ThresholdItem payloads."""
    id: int
    key: str
    value: float
    description: str | None = None


class ThresholdUpdate(BaseModel):
    """Pydantic schema for ThresholdUpdate payloads."""
    value: float


class ThresholdOverrideItem(BaseModel):
    """Scoped threshold override response."""

    id: int
    threshold_key: str
    value: float
    device_id: int | None = None
    device_type: str | None = None
    site: str | None = None
    description: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ThresholdOverrideCreate(BaseModel):
    """Create payload for a scoped threshold override."""

    threshold_key: str
    value: float
    device_id: int | None = None
    device_type: str | None = None
    site: str | None = None
    description: str | None = None


class MaintenanceWindowItem(BaseModel):
    """Maintenance window response."""

    id: int
    name: str
    device_id: int | None = None
    site: str | None = None
    starts_at: datetime
    ends_at: datetime
    reason: str | None = None
    is_active: bool
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class MaintenanceWindowCreate(BaseModel):
    """Create payload for alert suppression windows."""

    name: str
    device_id: int | None = None
    site: str | None = None
    starts_at: datetime
    ends_at: datetime
    reason: str | None = None


class DeviceTypeOption(BaseModel):
    """Pydantic schema for DeviceTypeOption payloads."""
    value: str
    label: str


class DeviceOption(BaseModel):
    """Pydantic schema for DeviceOption payloads."""
    id: int
    name: str
    ip_address: str
    device_type: str
    site: str | None = None
    location: str | None = None
    is_active: bool


class AuthObservabilitySummary(BaseModel):
    """Pydantic schema for AuthObservabilitySummary payloads."""
    active_sessions: int
    login_failures_window: int
    login_rate_limited_window: int
    revoked_sessions_window: int
