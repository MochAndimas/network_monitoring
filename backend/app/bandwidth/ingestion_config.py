"""Explicit router/exporter policy shared by ingestion and its durable checkpoint."""

import hashlib
import json
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

from .contracts import FlowPolicy


def strict_json(data: bytes | str) -> object:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def invalid_constant(_value: str) -> None:
        raise ValueError("nonfinite_json_number")

    return json.loads(data, object_pairs_hook=object_pairs, parse_constant=invalid_constant)


@dataclass(frozen=True, slots=True)
class IngestionPolicy:
    flow: FlowPolicy
    exporter: IPv4Address
    exporter_aliases: frozenset[IPv4Address] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.exporter, IPv4Address) or not isinstance(self.exporter_aliases, frozenset):
            raise ValueError("Exporter addresses must be immutable IPv4 values")
        if any(not isinstance(address, IPv4Address) for address in self.exporter_aliases):
            raise ValueError("Exporter aliases must be IPv4 values")
        if self.exporter in self.exporter_aliases:
            raise ValueError("Exporter aliases must not repeat the primary exporter")

    def accepts_exporter(self, address: object) -> bool:
        return isinstance(address, str) and (
            address == str(self.exporter) or any(address == str(ip) for ip in self.exporter_aliases)
        )

    @property
    def digest(self) -> str:
        value = {
            "version": 1,
            "router_id": self.flow.router_id,
            "exporter": str(self.exporter),
            "lan_interfaces": sorted(self.flow.lan_interfaces),
            "wan_interfaces": sorted(self.flow.wan_interfaces),
            "lan_networks": sorted(str(net) for net in self.flow.lan_networks),
            "excluded_remote_networks": sorted(str(net) for net in self.flow.excluded_remote_networks),
        }
        # Preserve existing stream digests for policies without aliases.
        if self.exporter_aliases:
            value["exporter_aliases"] = sorted(str(ip) for ip in self.exporter_aliases)
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def load_policy(path: Path) -> IngestionPolicy:
    """Reject unknown keys and type coercion before any source is processed."""
    data = strict_json(path.read_bytes())
    keys = {"router_id", "exporter", "lan_interfaces", "wan_interfaces", "lan_networks", "excluded_remote_networks"}
    if not isinstance(data, dict) or not keys <= set(data) or set(data) - keys - {"exporter_aliases"}:
        raise ValueError("Flow policy requires exactly the documented keys")
    for field in ("lan_interfaces", "wan_interfaces", "lan_networks", "excluded_remote_networks"):
        if not isinstance(data[field], list):
            raise ValueError("Flow policy collections must be arrays")
    if not isinstance(data["exporter"], str):
        raise ValueError("Exporter must be an IPv4 string")
    aliases = data.get("exporter_aliases", [])
    if not isinstance(aliases, list) or any(not isinstance(value, str) for value in aliases):
        raise ValueError("Exporter aliases must be an IPv4 string array")
    if len(aliases) != len(set(aliases)) or len(aliases) > 8:
        raise ValueError("Exporter aliases must be unique and limited to eight")
    for field in ("lan_networks", "excluded_remote_networks"):
        if any(not isinstance(value, str) for value in data[field]):
            raise ValueError("Networks must be CIDR strings")
    return IngestionPolicy(
        FlowPolicy(
            router_id=data["router_id"],
            lan_interfaces=frozenset(data["lan_interfaces"]),
            wan_interfaces=frozenset(data["wan_interfaces"]),
            lan_networks=tuple(IPv4Network(value) for value in data["lan_networks"]),
            excluded_remote_networks=tuple(IPv4Network(value) for value in data["excluded_remote_networks"]),
        ),
        IPv4Address(data["exporter"]),
        frozenset(IPv4Address(value) for value in aliases),
    )
