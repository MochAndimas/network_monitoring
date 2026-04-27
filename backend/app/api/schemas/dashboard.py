"""Define module logic for `backend/app/api/schemas/dashboard.py`.

This module contains project-specific implementation details.
"""

from datetime import date, datetime
from ipaddress import ip_address

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...core.constants import DEVICE_TYPE_CHOICES


class DashboardSummary(BaseModel):
    """Perform DashboardSummary.

    This class encapsulates related behavior and data for this domain area.
    """
    internet_status: str
    mikrotik_status: str
    server_status: str
    active_alerts: int


class DeviceListItem(BaseModel):
    """Perform DeviceListItem.

    This class encapsulates related behavior and data for this domain area.
    """
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
    """Perform PageMeta.

    This class encapsulates related behavior and data for this domain area.
    """
    total: int
    limit: int
    offset: int


class DeviceListPage(BaseModel):
    """Perform DeviceListPage.

    This class encapsulates related behavior and data for this domain area.
    """
    items: list["DeviceListItem"]
    meta: PageMeta


class DeviceCreate(BaseModel):
    """Perform DeviceCreate.

    This class encapsulates related behavior and data for this domain area.
    """
    name: str = Field(min_length=1, max_length=150)
    ip_address: str = Field(min_length=1, max_length=50)
    device_type: str = Field(min_length=1, max_length=50)
    site: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    is_active: bool = True

    @field_validator("ip_address")
    @classmethod
    def validate_ip_address(cls, value: str) -> str:
        """Validate IP address.

        Args:
            value: Parameter input untuk routine ini.

        Returns:
            TODO describe return value.

        """
        ip_address(value)
        return value

    @field_validator("device_type")
    @classmethod
    def validate_device_type(cls, value: str) -> str:
        """Validate device type.

        Args:
            value: Parameter input untuk routine ini.

        Returns:
            TODO describe return value.

        """
        if value not in DEVICE_TYPE_CHOICES:
            raise ValueError(f"device_type must be one of: {', '.join(DEVICE_TYPE_CHOICES)}")
        return value


class DeviceUpdate(BaseModel):
    """Perform DeviceUpdate.

    This class encapsulates related behavior and data for this domain area.
    """
    name: str | None = Field(default=None, min_length=1, max_length=150)
    ip_address: str | None = Field(default=None, min_length=1, max_length=50)
    device_type: str | None = Field(default=None, min_length=1, max_length=50)
    site: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None

    @field_validator("ip_address")
    @classmethod
    def validate_optional_ip_address(cls, value: str | None) -> str | None:
        """Validate optional IP address.

        Args:
            value: Parameter input untuk routine ini.

        Returns:
            TODO describe return value.

        """
        if value is None:
            return value
        ip_address(value)
        return value

    @field_validator("device_type")
    @classmethod
    def validate_optional_device_type(cls, value: str | None) -> str | None:
        """Validate optional device type.

        Args:
            value: Parameter input untuk routine ini.

        Returns:
            TODO describe return value.

        """
        if value is None:
            return value
        if value not in DEVICE_TYPE_CHOICES:
            raise ValueError(f"device_type must be one of: {', '.join(DEVICE_TYPE_CHOICES)}")
        return value


class MetricHistoryItem(BaseModel):
    """Perform MetricHistoryItem.

    This class encapsulates related behavior and data for this domain area.
    """
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
    """Perform MetricHistoryPage.

    This class encapsulates related behavior and data for this domain area.
    """
    items: list["MetricHistoryItem"]
    meta: PageMeta


class MetricDailySummaryItem(BaseModel):
    """Perform MetricDailySummaryItem.

    This class encapsulates related behavior and data for this domain area.
    """
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
    """Perform MetricDailySummaryPage.

    This class encapsulates related behavior and data for this domain area.
    """
    items: list["MetricDailySummaryItem"]
    meta: PageMeta


class AlertItem(BaseModel):
    """Perform AlertItem.

    This class encapsulates related behavior and data for this domain area.
    """
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
    """Perform AlertPage.

    This class encapsulates related behavior and data for this domain area.
    """
    items: list["AlertItem"]
    meta: PageMeta


class IncidentItem(BaseModel):
    """Perform IncidentItem.

    This class encapsulates related behavior and data for this domain area.
    """
    id: int
    device_id: int | None = None
    device_name: str | None = None
    status: str
    summary: str
    started_at: datetime
    ended_at: datetime | None = None


class IncidentPage(BaseModel):
    """Perform IncidentPage.

    This class encapsulates related behavior and data for this domain area.
    """
    items: list["IncidentItem"]
    meta: PageMeta


class RunCycleResult(BaseModel):
    """Perform RunCycleResult.

    This class encapsulates related behavior and data for this domain area.
    """
    metrics_collected: int
    alerts_created: int
    alerts_resolved: int
    incidents_created: int
    incidents_resolved: int


class ThresholdItem(BaseModel):
    """Perform ThresholdItem.

    This class encapsulates related behavior and data for this domain area.
    """
    id: int
    key: str
    value: float
    description: str | None = None


class ThresholdUpdate(BaseModel):
    """Perform ThresholdUpdate.

    This class encapsulates related behavior and data for this domain area.
    """
    value: float


class DeviceTypeOption(BaseModel):
    """Perform DeviceTypeOption.

    This class encapsulates related behavior and data for this domain area.
    """
    value: str
    label: str


class DeviceOption(BaseModel):
    """Perform DeviceOption.

    This class encapsulates related behavior and data for this domain area.
    """
    id: int
    name: str
    ip_address: str
    device_type: str
    site: str | None = None
    is_active: bool


class AuthObservabilitySummary(BaseModel):
    """Perform AuthObservabilitySummary.

    This class encapsulates related behavior and data for this domain area.
    """
    active_sessions: int
    login_failures_window: int
    login_rate_limited_window: int
    revoked_sessions_window: int
