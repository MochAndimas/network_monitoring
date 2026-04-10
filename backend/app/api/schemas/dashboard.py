from datetime import datetime
from ipaddress import ip_address

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...core.constants import DEVICE_TYPE_CHOICES


class DashboardSummary(BaseModel):
    internet_status: str
    mikrotik_status: str
    server_status: str
    active_alerts: int


class DeviceListItem(BaseModel):
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


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    ip_address: str = Field(min_length=1, max_length=50)
    device_type: str = Field(min_length=1, max_length=50)
    site: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    is_active: bool = True

    @field_validator("ip_address")
    @classmethod
    def validate_ip_address(cls, value: str) -> str:
        ip_address(value)
        return value

    @field_validator("device_type")
    @classmethod
    def validate_device_type(cls, value: str) -> str:
        if value not in DEVICE_TYPE_CHOICES:
            raise ValueError(f"device_type must be one of: {', '.join(DEVICE_TYPE_CHOICES)}")
        return value


class DeviceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    ip_address: str | None = Field(default=None, min_length=1, max_length=50)
    device_type: str | None = Field(default=None, min_length=1, max_length=50)
    site: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None

    @field_validator("ip_address")
    @classmethod
    def validate_optional_ip_address(cls, value: str | None) -> str | None:
        if value is None:
            return value
        ip_address(value)
        return value

    @field_validator("device_type")
    @classmethod
    def validate_optional_device_type(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in DEVICE_TYPE_CHOICES:
            raise ValueError(f"device_type must be one of: {', '.join(DEVICE_TYPE_CHOICES)}")
        return value


class MetricHistoryItem(BaseModel):
    id: int
    device_id: int
    device_name: str
    metric_name: str
    metric_value: str
    metric_value_numeric: float | None = None
    status: str | None = None
    unit: str | None = None
    checked_at: datetime


class AlertItem(BaseModel):
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
    id: int
    device_id: int | None = None
    device_name: str | None = None
    status: str
    summary: str
    started_at: datetime
    ended_at: datetime | None = None


class RunCycleResult(BaseModel):
    metrics_collected: int
    alerts_created: int
    alerts_resolved: int
    incidents_created: int
    incidents_resolved: int


class ThresholdItem(BaseModel):
    id: int
    key: str
    value: float
    description: str | None = None


class ThresholdUpdate(BaseModel):
    value: float


class DeviceTypeOption(BaseModel):
    value: str
    label: str
