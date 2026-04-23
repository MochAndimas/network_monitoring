"""Provide operator and maintenance scripts for the network monitoring project."""

import argparse
import asyncio

from pysnmp.hlapi.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
)


DEFAULT_TARGETS = [
    ("EPSON L3250 - 1", "192.168.88.38", "Epson1RO2047!"),
    ("EPSON L3250 - 2", "192.168.88.145", "Epson2RO2047!"),
]

DEFAULT_OIDS = [
    ("sysDescr", "1.3.6.1.2.1.1.1.0"),
    ("sysName", "1.3.6.1.2.1.1.5.0"),
    ("sysUpTime", "1.3.6.1.2.1.1.3.0"),
]


async def snmp_get(ip: str, community: str, oid: str, timeout: int, retries: int) -> tuple[bool, str]:
    engine = SnmpEngine()
    try:
        error_indication, error_status, _, var_binds = await get_cmd(
            engine,
            CommunityData(community, mpModel=1),
            await UdpTransportTarget.create((ip, 161), timeout=timeout, retries=retries),
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


async def run_targets(targets: list[tuple[str, str, str]], timeout: int, retries: int) -> None:
    for label, ip, community in targets:
        print(f"[{label}] {ip}")
        for oid_label, oid in DEFAULT_OIDS:
            ok, result = await snmp_get(ip, community, oid, timeout, retries)
            print(f"  {oid_label}: {'OK' if ok else 'FAIL'} | {result}")
        print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test SNMP v2c reachability to one or more targets.")
    parser.add_argument("--ip", help="Target IP address.")
    parser.add_argument("--community", help="SNMP v2c community string.")
    parser.add_argument("--label", default="Custom Target", help="Display label for custom target.")
    parser.add_argument("--timeout", type=int, default=2, help="Timeout in seconds per request.")
    parser.add_argument("--retries", type=int, default=1, help="Retry count per request.")
    return parser.parse_args()


def build_targets(args: argparse.Namespace) -> list[tuple[str, str, str]]:
    if args.ip and args.community:
        return [(args.label, args.ip, args.community)]
    if args.ip or args.community:
        raise SystemExit("Both --ip and --community must be provided together.")
    return DEFAULT_TARGETS


async def main() -> None:
    args = parse_args()
    await run_targets(build_targets(args), args.timeout, args.retries)


if __name__ == "__main__":
    asyncio.run(main())
