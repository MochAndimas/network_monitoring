"""Convert full DHCP/ARP observations into conservative, router-scoped identities."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from ipaddress import IPv4Address, ip_address


@dataclass(frozen=True, slots=True)
class ClientObservation:
    ip: str
    mac: str
    hostname: str | None
    source: str


@dataclass(frozen=True, slots=True)
class InventorySnapshot:
    router_id: int
    observed_ns: int
    clients: tuple[ClientObservation, ...]
    ambiguous_ips: tuple[str, ...]
    invalid_rows: int


class InventoryMetricBatch(list[dict]):
    """List-compatible collector result carrying observations to the write transaction."""

    def __init__(self, metrics: list[dict], snapshots: tuple[InventorySnapshot, ...]) -> None:
        super().__init__(metrics)
        self.snapshots = snapshots


def _pair(row: Mapping[str, object]) -> tuple[str, str] | None:
    try:
        address = ip_address(str(row.get("active-address") or row.get("address") or ""))
    except ValueError:
        return None
    if (
        not isinstance(address, IPv4Address)
        or address.is_unspecified
        or address.is_multicast
        or address == IPv4Address("255.255.255.255")
    ):
        return None
    mac = str(row.get("active-mac-address") or row.get("mac-address") or "").upper()
    if not re.fullmatch(r"[0-9A-F]{2}(?::[0-9A-F]{2}){5}", mac):
        return None
    if mac == "00:00:00:00:00:00" or int(mac[:2], 16) & 1:
        return None
    return str(address), mac


def build_inventory_snapshot(
    router_id: int,
    observed_ns: int,
    dhcp_leases: Sequence[Mapping[str, object]],
    arp_entries: Sequence[Mapping[str, object]],
) -> InventorySnapshot:
    """Use bound leases and reachable/permanent ARP, never an incomplete fetch.

    Contradictory IP→MAC observations are excluded, not resolved by guessing.
    This records identity evidence, not a promise that the client is online.
    """
    if type(router_id) is not int or router_id <= 0:
        raise ValueError("router_id must be a positive integer")
    if type(observed_ns) is not int or not 0 < observed_ns < (1 << 63) - 1:
        raise ValueError("observed_ns must be a positive signed BIGINT with boundary headroom")
    candidates: dict[str, dict[str, ClientObservation]] = {}
    invalid = 0
    for source, rows in (("dhcp", dhcp_leases), ("arp", arp_entries)):
        for row in rows:
            if source == "dhcp" and str(row.get("status", "")).lower() != "bound":
                continue
            if source == "arp" and str(row.get("status", "")).lower() not in {"reachable", "permanent"}:
                continue
            pair = _pair(row)
            if pair is None:
                invalid += 1
                continue
            ip, mac = pair
            raw_hostname = row.get("active-host-name") or row.get("host-name")
            hostname = str(raw_hostname).strip()[:255] if source == "dhcp" and raw_hostname else None
            current = candidates.setdefault(ip, {}).get(mac)
            if current is None or source == "dhcp":
                candidates[ip][mac] = ClientObservation(ip, mac, hostname or None, source)
    ambiguous = {ip for ip, owners in candidates.items() if len(owners) > 1}
    clients = tuple(next(iter(owners.values())) for ip, owners in sorted(candidates.items()) if ip not in ambiguous)
    return InventorySnapshot(router_id, observed_ns, clients, tuple(sorted(ambiguous)), invalid)
