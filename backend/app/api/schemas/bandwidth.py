"""Bandwidth counters are decimal strings to preserve browser integer precision."""

from datetime import date
from typing import Literal

from pydantic import BaseModel


class IdentityObservation(BaseModel):
    display_name: str
    mac_address: str
    observed_ns: str


class UsageRow(BaseModel):
    day: date | None = None
    subject: str | None = None
    client_id: int | None = None
    display_name: str | None = None
    unresolved_ip: str | None = None
    latest_observation: IdentityObservation | None = None
    upload_bytes: str
    download_bytes: str
    total_bytes: str
    estimated_bytes: str
    unresolved_bytes: str
    updated_ns: str


class UsagePage(BaseModel):
    router_id: int
    start: date
    end: date
    timezone: Literal["Asia/Jakarta"] = "Asia/Jakarta"
    allocation: Literal["proportional_integer_v1"] = "proportional_integer_v1"
    completeness: Literal["unverified"] = "unverified"
    items: list[UsageRow]
    limit: int
    offset: int
    has_more: bool


class ClientRow(BaseModel):
    id: int
    mac_address: str
    hostname: str | None
    custom_name: str | None
    display_name: str
    first_seen_ns: str
    last_seen_ns: str


class ClientPage(BaseModel):
    items: list[ClientRow]
    next_after_id: int | None
