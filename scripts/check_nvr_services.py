"""Check reachable NVR services from the current machine.

Usage:
    python scripts/check_nvr_services.py 192.168.88.171
    python scripts/check_nvr_services.py 192.168.88.171 --ports 80,3000,554,30080
"""

from __future__ import annotations

import argparse
import asyncio
import socket
import time
from dataclasses import dataclass
from http.client import HTTPConnection

from pysnmp.hlapi.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
)


DEFAULT_PORTS = [
    80,
    443,
    554,
    8554,
    3000,
    3002,
    30080,
    33000,
    34002,
    8000,
    8080,
    8899,
]

SERVICE_HINTS = {
    80: "HTTP/Web/ONVIF candidate",
    443: "HTTPS/Web candidate",
    554: "RTSP",
    8554: "RTSP alternate",
    3000: "Tiandy Server Port",
    3002: "Tiandy Data Port (WS)",
    30080: "PoE channel mapped HTTP",
    33000: "PoE channel mapped Server Port",
    34002: "PoE channel mapped Data Port (WS)",
    8000: "SDK/ONVIF candidate",
    8080: "HTTP/ONVIF alternate",
    8899: "ONVIF candidate",
}

SNMP_OIDS = [
    ("sysDescr", "1.3.6.1.2.1.1.1.0"),
    ("sysName", "1.3.6.1.2.1.1.5.0"),
    ("sysUpTime", "1.3.6.1.2.1.1.3.0"),
]


@dataclass(frozen=True)
class PortResult:
    port: int
    open: bool
    elapsed_ms: float
    error: str | None = None


def parse_ports(raw_ports: str | None) -> list[int]:
    if not raw_ports:
        return DEFAULT_PORTS
    ports: list[int] = []
    for raw_port in raw_ports.split(","):
        item = raw_port.strip()
        if not item:
            continue
        ports.append(int(item))
    return list(dict.fromkeys(ports))


def check_tcp_port(host: str, port: int, timeout_seconds: float) -> PortResult:
    started_at = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            return PortResult(port=port, open=True, elapsed_ms=elapsed_ms)
    except OSError as exc:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        return PortResult(port=port, open=False, elapsed_ms=elapsed_ms, error=str(exc))


def check_http(host: str, port: int, timeout_seconds: float) -> str:
    try:
        connection = HTTPConnection(host, port=port, timeout=timeout_seconds)
        connection.request("GET", "/")
        response = connection.getresponse()
        response.read(256)
        return f"HTTP {response.status} {response.reason}"
    except OSError as exc:
        return f"HTTP failed: {exc}"
    finally:
        try:
            connection.close()
        except Exception:
            pass


async def snmp_get(host: str, community: str, oid: str, timeout_seconds: float, retries: int) -> tuple[bool, str]:
    engine = SnmpEngine()
    try:
        error_indication, error_status, _, var_binds = await get_cmd(
            engine,
            CommunityData(community, mpModel=1),
            await UdpTransportTarget.create((host, 161), timeout=timeout_seconds, retries=retries),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )
        if error_indication:
            return False, f"error={error_indication}"
        if error_status:
            return False, f"error={error_status.prettyPrint()}"
        rendered = "; ".join(f"{name.prettyPrint()}={value.prettyPrint()}" for name, value in var_binds)
        return True, rendered
    except Exception as exc:
        return False, f"exception={exc}"
    finally:
        try:
            engine.transport_dispatcher.close_dispatcher()
        except Exception:
            pass


async def check_snmp(host: str, community: str, timeout_seconds: float, retries: int) -> None:
    print()
    print(f"SNMP v2c probes on UDP 161 with community '{community}':")
    for oid_label, oid in SNMP_OIDS:
        ok, result = await snmp_get(host, community, oid, timeout_seconds, retries)
        state = "OK" if ok else "FAIL"
        print(f"{oid_label:<9} {state:<5} {result}")


def format_result(host: str, result: PortResult) -> str:
    state = "OPEN" if result.open else "closed"
    hint = SERVICE_HINTS.get(result.port, "custom")
    suffix = "" if result.open else f" | {result.error}"
    return f"{host}:{result.port:<5} {state:<6} {result.elapsed_ms:>7.1f} ms | {hint}{suffix}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Check NVR TCP/HTTP service reachability.")
    parser.add_argument("host", help="NVR IP address or hostname, e.g. 192.168.88.171")
    parser.add_argument(
        "--ports",
        help="Comma-separated TCP ports to test. Defaults to common Tiandy/Web/RTSP/ONVIF ports.",
    )
    parser.add_argument("--timeout", type=float, default=1.5, help="TCP/HTTP timeout in seconds.")
    parser.add_argument("--http", action="store_true", help="Also send HTTP GET / to open HTTP-like ports.")
    parser.add_argument("--snmp", action="store_true", help="Also check SNMP v2c on UDP 161.")
    parser.add_argument("--community", default="public", help="SNMP v2c community string.")
    parser.add_argument("--snmp-retries", type=int, default=1, help="SNMP retry count per OID.")
    args = parser.parse_args()

    ports = parse_ports(args.ports)
    print(f"Checking {args.host} from this machine")
    print(f"Ports: {', '.join(str(port) for port in ports)}")
    print()

    open_ports: list[int] = []
    for port in ports:
        result = check_tcp_port(args.host, port, args.timeout)
        print(format_result(args.host, result))
        if result.open:
            open_ports.append(port)

    if args.http and open_ports:
        print()
        print("HTTP probes:")
        for port in open_ports:
            if port in {80, 443, 8080, 8443, 30080}:
                print(f"{args.host}:{port:<5} {check_http(args.host, port, args.timeout)}")

    print()
    if open_ports:
        print(f"Open ports: {', '.join(str(port) for port in open_ports)}")
    else:
        print("No tested TCP ports are reachable from this machine.")

    if args.snmp:
        asyncio.run(check_snmp(args.host, args.community, args.timeout, args.snmp_retries))


if __name__ == "__main__":
    main()
