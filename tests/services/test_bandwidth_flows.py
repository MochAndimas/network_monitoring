"""Accounting contracts based on the observed GoFlow2 NAT representation."""

from dataclasses import replace
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv4Network

import pytest

from backend.app.bandwidth import (
    Direction,
    FlowPolicy,
    FlowRejected,
    RejectionReason,
    classify_flow,
    normalize_flow,
)


@pytest.fixture
def policy():
    return FlowPolicy(
        router_id=1,
        lan_interfaces=frozenset({13}),
        wan_interfaces=frozenset({10}),
        lan_networks=(IPv4Network("192.168.1.0/24"),),
        excluded_remote_networks=(IPv4Network("10.0.0.0/8"), IPv4Network("192.168.0.0/16")),
    )


@pytest.fixture
def record():
    return {
        "type": "IPFIX",
        "src_addr": "192.168.1.66",
        "dst_addr": "142.251.10.95",
        "post_nat_src_addr": "67714e96",
        "post_nat_dst_addr": "8efb0a5f",
        "in_if": 13,
        "out_if": 10,
        "bytes": 4178,
        "packets": 11,
        "time_flow_start_ns": 1792044279950000001,
        "time_flow_end_ns": 1792044280950000003,
        "time_received_ns": 1792044296154433709,
    }


def test_observed_upload_preserves_exact_bytes_times_and_input(record, policy):
    original = record.copy()
    flow = normalize_flow(record)
    result = classify_flow(flow, policy)
    assert result.router_id == 1
    assert result.direction == Direction.UPLOAD
    assert result.device_ip == IPv4Address("192.168.1.66")
    assert result.remote_ip == IPv4Address("142.251.10.95")
    assert flow.post_nat_source == IPv4Address("103.113.78.150")
    assert flow.post_nat_destination == result.remote_ip
    assert flow.bytes == 4178
    assert flow.received_ns == 1792044296154433709
    assert record == original


def test_download_uses_translated_internal_destination(record, policy):
    record.update(
        src_addr="104.16.102.112",
        dst_addr="103.113.78.150",
        post_nat_src_addr="68106670",
        post_nat_dst_addr="c0a80145",
        in_if=10,
        out_if=13,
    )
    result = classify_flow(normalize_flow(record), policy)
    assert result.direction == Direction.DOWNLOAD
    assert result.device_ip == IPv4Address("192.168.1.69")
    assert result.remote_ip == IPv4Address("104.16.102.112")


@pytest.mark.parametrize("nat", [None, "", "00000000", "0.0.0.0"])
def test_non_nat_routed_download_can_use_direct_internal_destination(record, policy, nat):
    record.update(src_addr="104.16.102.112", dst_addr="192.168.1.69", post_nat_dst_addr=nat, in_if=10, out_if=13)
    assert classify_flow(normalize_flow(record), policy).device_ip == IPv4Address("192.168.1.69")


def test_missing_nat_never_attributes_download_to_public_router(record, policy):
    record.update(src_addr="104.16.102.112", dst_addr="103.113.78.150", in_if=10, out_if=13)
    record.pop("post_nat_dst_addr")
    with pytest.raises(FlowRejected) as error:
        classify_flow(normalize_flow(record), policy)
    assert error.value.reason == RejectionReason.MISSING_DEVICE_ADDRESS


@pytest.mark.parametrize("value", ["192.168.1.69", "c0a80145", "C0A80145"])
def test_nat_accepts_only_documented_dotted_or_hex_representations(record, value):
    record["post_nat_dst_addr"] = value
    assert normalize_flow(record).post_nat_destination == IPv4Address("192.168.1.69")


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("type", "NETFLOW_V9", RejectionReason.UNSUPPORTED_TYPE),
        ("src_addr", "not-an-ip", RejectionReason.INVALID_ADDRESS),
        ("src_addr", "0.0.0.0", RejectionReason.INVALID_ADDRESS),
        ("src_addr", "2001:db8::1", RejectionReason.UNSUPPORTED_ADDRESS),
        ("post_nat_dst_addr", "wKgBRQ==", RejectionReason.INVALID_ADDRESS),
        ("post_nat_dst_addr", 3232235845, RejectionReason.INVALID_ADDRESS),
        ("bytes", -1, RejectionReason.INVALID_INTEGER),
        ("bytes", True, RejectionReason.INVALID_INTEGER),
        ("bytes", "4178", RejectionReason.INVALID_INTEGER),
        ("bytes", 4178.5, RejectionReason.INVALID_INTEGER),
        ("bytes", 2**63, RejectionReason.INVALID_INTEGER),
        ("bytes", 0, RejectionReason.EMPTY_FLOW),
        ("packets", None, RejectionReason.INVALID_INTEGER),
        ("in_if", 2**32, RejectionReason.INVALID_INTEGER),
        ("time_flow_start_ns", 0, RejectionReason.INVALID_TIMESTAMP),
        ("time_flow_end_ns", 1, RejectionReason.INVALID_TIMESTAMP),
        ("time_received_ns", 0, RejectionReason.INVALID_TIMESTAMP),
    ],
)
def test_malformed_records_have_stable_safe_rejection_reason(record, field, value, reason):
    record[field] = value
    with pytest.raises(FlowRejected) as error:
        normalize_flow(record)
    assert error.value.reason == reason
    assert "192.168" not in str(error.value)


@pytest.mark.parametrize("field", ["bytes", "packets", "in_if", "out_if", "time_flow_end_ns", "src_addr"])
def test_required_fields_are_never_silently_defaulted(record, field):
    record.pop(field)
    with pytest.raises(FlowRejected):
        normalize_flow(record)


@pytest.mark.parametrize("interfaces", [(13, 0), (0, 13), (13, 13), (10, 10), (40, 13)])
def test_router_local_lan_and_unknown_interface_traffic_are_rejected(record, policy, interfaces):
    record["in_if"], record["out_if"] = interfaces
    with pytest.raises(FlowRejected) as error:
        classify_flow(normalize_flow(record), policy)
    assert error.value.reason == RejectionReason.UNCLASSIFIED_INTERFACE


@pytest.mark.parametrize("remote", ["192.168.223.1", "192.168.1.5", "10.10.0.1", "224.0.0.1", "255.255.255.255"])
def test_explicit_remote_exclusions_apply_in_both_directions(record, policy, remote):
    for direction in ("upload", "download"):
        candidate = record.copy()
        if direction == "upload":
            candidate["dst_addr"] = remote
        else:
            candidate.update(
                src_addr=remote, dst_addr="103.113.78.150", post_nat_dst_addr="c0a80145", in_if=10, out_if=13
            )
        with pytest.raises(FlowRejected) as error:
            classify_flow(normalize_flow(candidate), policy)
        assert error.value.reason == RejectionReason.EXCLUDED_REMOTE


def test_router_scope_and_interfaces_are_supplied_independently(record, policy):
    other_policy = replace(policy, router_id=2, lan_interfaces=frozenset({20}), wan_interfaces=frozenset({30}))
    record.update(in_if=20, out_if=30)
    assert classify_flow(normalize_flow(record), other_policy).router_id == 2
    with pytest.raises(FlowRejected):
        classify_flow(normalize_flow(record), policy)


def test_outside_lan_upload_is_not_counted(record, policy):
    record["src_addr"] = "192.168.2.66"
    with pytest.raises(FlowRejected) as error:
        classify_flow(normalize_flow(record), policy)
    assert error.value.reason == RejectionReason.DEVICE_OUTSIDE_LAN


@pytest.mark.parametrize(
    "changes",
    [
        {"router_id": True},
        {"router_id": 0},
        {"lan_interfaces": frozenset()},
        {"lan_interfaces": frozenset({10})},
        {"wan_interfaces": frozenset({True})},
        {"lan_networks": ()},
        {"lan_networks": ("192.168.1.0/24",)},
    ],
)
def test_invalid_policy_fails_before_records_are_processed(policy, changes):
    with pytest.raises(ValueError):
        replace(policy, **changes)


def test_midnight_and_late_arrival_preserve_flow_time_instead_of_assigning_receive_date(record):
    # WIB midnight is 17:00 UTC. Exact nanoseconds remain available for later
    # explicit daily allocation; this stage does not invent per-day byte totals.
    midnight = int(datetime(2026, 10, 15, 17, tzinfo=UTC).timestamp()) * 10**9
    record.update(
        time_flow_start_ns=midnight - 1, time_flow_end_ns=midnight + 1, time_received_ns=midnight + 3600 * 10**9
    )
    flow = normalize_flow(record)
    assert flow.started_ns == midnight - 1
    assert flow.ended_ns == midnight + 1
    assert flow.received_ns - midnight == 3600 * 10**9


def test_clock_skew_and_zero_duration_are_preserved(record):
    record.update(time_flow_end_ns=record["time_flow_start_ns"], time_received_ns=record["time_flow_start_ns"] - 1)
    assert normalize_flow(record).ended_ns == record["time_flow_start_ns"]


def test_unknown_fields_do_not_break_compatibility(record):
    expected = normalize_flow(record)
    record["future_exporter_metadata"] = {"version": 2}
    assert normalize_flow(record) == expected


@pytest.mark.parametrize("record", [None, [], "not-json"])
def test_non_objects_have_explicit_rejection(record):
    with pytest.raises(FlowRejected) as error:
        normalize_flow(record)
    assert error.value.reason == RejectionReason.INVALID_RECORD
