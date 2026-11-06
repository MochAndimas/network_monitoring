"""Normalize decoded GoFlow2 IPFIX JSON objects without I/O or global settings."""

from collections.abc import Mapping
from ipaddress import IPv4Address, ip_address

from .contracts import FlowRejected, NormalizedFlow, RejectionReason

# The first storage implementation targets signed BIGINT in MySQL. Preserve
# nanoseconds exactly and reject overflow instead of rounding or wrapping it.
MAX_STORAGE_INTEGER = (1 << 63) - 1


def _integer(record: Mapping[str, object], field: str, maximum: int = MAX_STORAGE_INTEGER) -> int:
    value = record.get(field)
    if type(value) is not int or not 0 <= value <= maximum:
        raise FlowRejected(RejectionReason.INVALID_INTEGER, field)
    return value


def _address(record: Mapping[str, object], field: str, *, nat: bool = False) -> IPv4Address | None:
    value = record.get(field)
    if nat and (value is None or value == ""):
        return None
    if not isinstance(value, str):
        raise FlowRejected(RejectionReason.INVALID_ADDRESS, field)
    try:
        # Custom protobuf bytes in the verified mapping are exactly four bytes
        # represented as eight hex digits. Base64 is deliberately not guessed.
        if nat and len(value) == 8 and all(char in "0123456789abcdefABCDEF" for char in value):
            address = ip_address(bytes.fromhex(value))
        else:
            address = ip_address(value)
    except ValueError:
        raise FlowRejected(RejectionReason.INVALID_ADDRESS, field) from None
    if not isinstance(address, IPv4Address):
        raise FlowRejected(RejectionReason.UNSUPPORTED_ADDRESS, field)
    if address.is_unspecified:
        if nat:
            return None
        raise FlowRejected(RejectionReason.INVALID_ADDRESS, field)
    return address


def normalize_flow(record: Mapping[str, object]) -> NormalizedFlow:
    """Validate one decoded object; unknown fields are ignored for compatibility.

    Missing timestamps/counters are errors, not zero samples. NetFlow v9 is
    excluded to avoid silently accounting records without the tested NAT mapping.
    Arrival may precede flow end slightly due to router clock skew; the raw times
    are preserved for the later ingestion layer to assess, never replaced by now.
    """
    if not isinstance(record, Mapping):
        raise FlowRejected(RejectionReason.INVALID_RECORD)
    if record.get("type") != "IPFIX":
        raise FlowRejected(RejectionReason.UNSUPPORTED_TYPE, "type")
    source = _address(record, "src_addr")
    destination = _address(record, "dst_addr")
    assert source is not None and destination is not None
    started = _integer(record, "time_flow_start_ns")
    ended = _integer(record, "time_flow_end_ns")
    received = _integer(record, "time_received_ns")
    if started == 0 or ended < started or received == 0:
        raise FlowRejected(RejectionReason.INVALID_TIMESTAMP)
    size = _integer(record, "bytes")
    if size == 0:
        raise FlowRejected(RejectionReason.EMPTY_FLOW, "bytes")
    return NormalizedFlow(
        source=source,
        destination=destination,
        post_nat_source=_address(record, "post_nat_src_addr", nat=True),
        post_nat_destination=_address(record, "post_nat_dst_addr", nat=True),
        input_interface=_integer(record, "in_if", 0xFFFFFFFF),
        output_interface=_integer(record, "out_if", 0xFFFFFFFF),
        bytes=size,
        packets=_integer(record, "packets"),
        started_ns=started,
        ended_ns=ended,
        received_ns=received,
    )
