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
    meta: PageMeta


class DeviceCreate(BaseModel):
    """Pydantic schema for DeviceCreate payloads."""
    name: str = Field(min_length=1, max_length=150)
    ip_address: str = Field(min_length=1, max_length=50)
    device_type: str = Field(min_length=1, max_length=50)
    site: str | None = Field(default=None, max_length=100)
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


class DeviceUpdate(BaseModel):
    """Pydantic schema for DeviceUpdate payloads."""
    name: str | None = Field(default=None, min_length=1, max_length=150)
    ip_address: str | None = Field(default=None, min_length=1, max_length=50)
    device_type: str | None = Field(default=None, min_length=1, max_length=50)
    site: str | None = Field(default=None, max_length=100)
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
    meta: PageMeta


class MetricHistoryCursorPage(BaseModel):
    """Pydantic schema for cursor-capable MetricHistoryItem pages."""
    items: list["MetricHistoryItem"]
    meta: CursorPageMeta


class MetricDailySummaryItem(BaseModel):
    """Pydantic schema for MetricDailySummaryItem payloads."""
    id: int
    device_id: int
    device_name: str
    device_type: str | None = None
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


class AlertItem(BaseModel):
    """Pydantic schema for AlertItem payloads."""
    id: int
    device_id: int | None = None
    device_name: str | None = None
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
    status: str
    summary: str
    started_at: datetime
    ended_at: datetime | None = None


class IncidentPage(BaseModel):
    """Pydantic schema for IncidentPage payloads."""
    items: list["IncidentItem"]
    meta: PageMeta


class RunCycleResult(BaseModel):
    """Pydantic schema for RunCycleResult payloads."""
    metrics_collected: int
    alerts_created: int
    alerts_resolved: int
    incidents_created: int
    incidents_resolved: int


class ThresholdItem(BaseModel):
    """Pydantic schema for ThresholdItem payloads."""
    id: int
    key: str
    value: float
    description: str | None = None


class ThresholdUpdate(BaseModel):
    """Pydantic schema for ThresholdUpdate payloads."""
    value: float


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
    is_active: bool


class AuthObservabilitySummary(BaseModel):
    """Pydantic schema for AuthObservabilitySummary payloads."""
    active_sessions: int
    login_failures_window: int
    login_rate_limited_window: int
    revoked_sessions_window: int
