"""Provide API response and request schemas for the network monitoring project."""

from datetime import datetime
from ipaddress import ip_address

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...core.constants import DEVICE_TYPE_CHOICES


class DashboardSummary(BaseModel):
    """Represent dashboard summary behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    internet_status: str
    mikrotik_status: str
    server_status: str
    active_alerts: int


class DeviceListItem(BaseModel):
    """Represent device list item behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
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
    """Represent page meta behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    total: int
    limit: int
    offset: int


class DeviceListPage(BaseModel):
    """Represent device list page behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    items: list["DeviceListItem"]
    meta: PageMeta


class DeviceCreate(BaseModel):
    """Represent device create behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
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
        """Validate ip address for API response and request schemas.

        Args:
            value: value value used by this routine (type `str`).

        Returns:
            `str` result produced by the routine.
        """
        ip_address(value)
        return value

    @field_validator("device_type")
    @classmethod
    def validate_device_type(cls, value: str) -> str:
        """Validate device type for API response and request schemas.

        Args:
            value: value value used by this routine (type `str`).

        Returns:
            `str` result produced by the routine.
        """
        if value not in DEVICE_TYPE_CHOICES:
            raise ValueError(f"device_type must be one of: {', '.join(DEVICE_TYPE_CHOICES)}")
        return value


class DeviceUpdate(BaseModel):
    """Represent device update behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
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
        """Validate optional ip address for API response and request schemas.

        Args:
            value: value value used by this routine (type `str | None`).

        Returns:
            `str | None` result produced by the routine.
        """
        if value is None:
            return value
        ip_address(value)
        return value

    @field_validator("device_type")
    @classmethod
    def validate_optional_device_type(cls, value: str | None) -> str | None:
        """Validate optional device type for API response and request schemas.

        Args:
            value: value value used by this routine (type `str | None`).

        Returns:
            `str | None` result produced by the routine.
        """
        if value is None:
            return value
        if value not in DEVICE_TYPE_CHOICES:
            raise ValueError(f"device_type must be one of: {', '.join(DEVICE_TYPE_CHOICES)}")
        return value


class MetricHistoryItem(BaseModel):
    """Represent metric history item behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
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
    """Represent metric history page behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    items: list["MetricHistoryItem"]
    meta: PageMeta


class AlertItem(BaseModel):
    """Represent alert item behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
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


class IncidentItem(BaseModel):
    """Represent incident item behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    id: int
    device_id: int | None = None
    device_name: str | None = None
    status: str
    summary: str
    started_at: datetime
    ended_at: datetime | None = None


class RunCycleResult(BaseModel):
    """Represent run cycle result behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    metrics_collected: int
    alerts_created: int
    alerts_resolved: int
    incidents_created: int
    incidents_resolved: int


class ThresholdItem(BaseModel):
    """Represent threshold item behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    id: int
    key: str
    value: float
    description: str | None = None


class ThresholdUpdate(BaseModel):
    """Represent threshold update behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    value: float


class DeviceTypeOption(BaseModel):
    """Represent device type option behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    value: str
    label: str


class DeviceOption(BaseModel):
    """Represent device option behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    id: int
    name: str
    ip_address: str
    device_type: str
    site: str | None = None
    is_active: bool


class AuthObservabilitySummary(BaseModel):
    """Represent auth observability summary behavior and data for API response and request schemas.

    Inherits from `BaseModel` to match the surrounding framework or persistence model.
    """
    active_sessions: int
    login_failures_window: int
    login_rate_limited_window: int
    revoked_sessions_window: int
