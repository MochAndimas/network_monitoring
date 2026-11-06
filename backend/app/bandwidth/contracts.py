"""Immutable contracts for one explicitly identified router's IPv4 flow stream."""

from dataclasses import dataclass
from enum import StrEnum
from ipaddress import IPv4Address, IPv4Network


class RejectionReason(StrEnum):
    INVALID_RECORD = "invalid_record"
    UNSUPPORTED_TYPE = "unsupported_type"
    UNSUPPORTED_ADDRESS = "unsupported_address"
    INVALID_ADDRESS = "invalid_address"
    INVALID_INTEGER = "invalid_integer"
    INVALID_TIMESTAMP = "invalid_timestamp"
    EMPTY_FLOW = "empty_flow"
    UNCLASSIFIED_INTERFACE = "unclassified_interface"
    MISSING_DEVICE_ADDRESS = "missing_device_address"
    DEVICE_OUTSIDE_LAN = "device_outside_lan"
    EXCLUDED_REMOTE = "excluded_remote"


class FlowRejected(ValueError):
    """Safe, bounded diagnostics; never include the raw record in an error."""

    def __init__(self, reason: RejectionReason, field: str = "") -> None:
        self.reason = reason
        self.field = field
        super().__init__(f"{reason.value}: {field}" if field else reason.value)


class Direction(StrEnum):
    UPLOAD = "upload"
    DOWNLOAD = "download"


@dataclass(frozen=True, slots=True)
class FlowPolicy:
    """Typed configuration supplied by the caller, never inferred from a client IP.

    Exclusions are explicit: private networks reachable through WAN may be VPN or
    upstream services. Interface direction alone does not establish internet usage.
    """

    router_id: int
    lan_interfaces: frozenset[int]
    wan_interfaces: frozenset[int]
    lan_networks: tuple[IPv4Network, ...]
    excluded_remote_networks: tuple[IPv4Network, ...]

    def __post_init__(self) -> None:
        if type(self.router_id) is not int or self.router_id <= 0:
            raise ValueError("router_id must be a positive integer")
        for interfaces in (self.lan_interfaces, self.wan_interfaces):
            if not isinstance(interfaces, frozenset) or not interfaces:
                raise ValueError("interface sets must be nonempty frozensets")
            if any(type(index) is not int or not 0 < index <= 0xFFFFFFFF for index in interfaces):
                raise ValueError("interface indexes must be positive uint32 integers")
        if self.lan_interfaces & self.wan_interfaces:
            raise ValueError("LAN and WAN interfaces must not overlap")
        if not self.lan_networks:
            raise ValueError("at least one LAN network is required")
        for networks in (self.lan_networks, self.excluded_remote_networks):
            if not isinstance(networks, tuple) or any(not isinstance(net, IPv4Network) for net in networks):
                raise ValueError("networks must be tuples of IPv4Network")


@dataclass(frozen=True, slots=True)
class NormalizedFlow:
    """Exact integer nanosecond timestamps and counters; no float conversion."""

    source: IPv4Address
    destination: IPv4Address
    post_nat_source: IPv4Address | None
    post_nat_destination: IPv4Address | None
    input_interface: int
    output_interface: int
    bytes: int
    packets: int
    started_ns: int
    ended_ns: int
    received_ns: int


@dataclass(frozen=True, slots=True)
class ClassifiedFlow:
    router_id: int
    direction: Direction
    device_ip: IPv4Address
    remote_ip: IPv4Address
    flow: NormalizedFlow
