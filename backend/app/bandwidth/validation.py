"""Versioned transfer baselines and exact integer comparison, without I/O."""

import re
from dataclasses import asdict, dataclass
from ipaddress import IPv4Address


@dataclass(frozen=True, slots=True)
class TransferBaseline:
    router_id: int
    policy_digest: str
    device_ip: str
    created_ns: str
    last_flow_id: str
    version: int = 1

    @classmethod
    def parse(cls, value: object) -> "TransferBaseline":
        fields = {"version", "router_id", "policy_digest", "device_ip", "created_ns", "last_flow_id"}
        if not isinstance(value, dict) or set(value) != fields:
            raise ValueError("invalid_baseline")
        if type(value["version"]) is not int or value["version"] != 1:
            raise ValueError("unsupported_baseline_version")
        if type(value["router_id"]) is not int or value["router_id"] <= 0:
            raise ValueError("invalid_baseline_router")
        if not isinstance(value["policy_digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["policy_digest"]):
            raise ValueError("invalid_baseline_policy")
        if not isinstance(value["device_ip"], str) or str(IPv4Address(value["device_ip"])) != value["device_ip"]:
            raise ValueError("invalid_baseline_address")
        for field, minimum in (("created_ns", 1), ("last_flow_id", 0)):
            raw = value[field]
            if (
                not isinstance(raw, str)
                or not re.fullmatch(r"0|[1-9][0-9]{0,18}", raw)
                or not minimum <= int(raw) <= 2**63 - 1
            ):
                raise ValueError("invalid_baseline_counter")
        return cls(**value)

    def payload(self) -> dict:
        return asdict(self)


def compare_transfer(observed: dict[str, int], expected: dict[str, int], tolerance_bps: int) -> dict:
    """A tolerance match is evidence about this window, never proof of completeness.

    IPFIX counts network bytes whereas expected sizes are usually application
    payloads. Background traffic and delayed flows can also enter this window.
    """
    if type(tolerance_bps) is not int or not 0 <= tolerance_bps <= 10000:
        raise ValueError("invalid_tolerance")
    if not expected or set(expected) - {"upload", "download"}:
        raise ValueError("expected_direction_required")
    directions = {}
    for direction, target in expected.items():
        actual = observed.get(direction)
        if type(target) is not int or target <= 0 or type(actual) is not int or actual < 0:
            raise ValueError("invalid_transfer_counter")
        # An empty observation window must never pass a positive transfer test,
        # even when an operator chooses a very permissive tolerance.
        within = actual > 0 and abs(actual - target) * 10000 <= target * tolerance_bps
        directions[direction] = {
            "expected_payload_bytes": str(target),
            "observed_network_bytes": str(actual),
            "within_tolerance": within,
        }
    return {
        "verdict": "within_tolerance"
        if all(row["within_tolerance"] for row in directions.values())
        else "outside_tolerance",
        "tolerance_bps": tolerance_bps,
        "directions": directions,
        "completeness": "unverified",
        "scope": "newly_committed_flows_for_device_ip",
    }
