"""Command-line utility for test snmp."""

import argparse
import asyncio
import os

from pysnmp.hlapi.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
)

DEFAULT_OIDS = [
    ("sysDescr", "1.3.6.1.2.1.1.1.0"),
    ("sysName", "1.3.6.1.2.1.1.5.0"),
    ("sysUpTime", "1.3.6.1.2.1.1.3.0"),
]


async def snmp_get(ip: str, community: str, oid: str, timeout: int, retries: int) -> tuple[bool, str]:
    """Return snmp get for the command-line workflow."""
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
    """Run targets for the command-line workflow."""
    for label, ip, community in targets:
        print(f"[{label}] {ip}")
        for oid_label, oid in DEFAULT_OIDS:
            ok, result = await snmp_get(ip, community, oid, timeout, retries)
            print(f"  {oid_label}: {'OK' if ok else 'FAIL'} | {result}")
        print()


def parse_args() -> argparse.Namespace:
    """Parse args for the command-line workflow."""
    parser = argparse.ArgumentParser(description="Test SNMP v2c reachability to one or more targets.")
    parser.add_argument("--ip", required=True, help="Target IP address.")
    parser.add_argument(
        "--community",
        default=os.getenv("SNMP_COMMUNITY"),
        help="SNMP v2c community string. Prefer SNMP_COMMUNITY environment variable to avoid shell history.",
    )
    parser.add_argument("--label", default="Custom Target", help="Display label for custom target.")
    parser.add_argument("--timeout", type=int, default=2, help="Timeout in seconds per request.")
    parser.add_argument("--retries", type=int, default=1, help="Retry count per request.")
    return parser.parse_args()


def build_targets(args: argparse.Namespace) -> list[tuple[str, str, str]]:
    """Build targets for the command-line workflow."""
    if not args.community:
        raise SystemExit("Provide SNMP community through SNMP_COMMUNITY or --community.")
    return [(args.label, args.ip, args.community)]


async def main() -> None:
    """Run the command-line workflow from parsed arguments."""
    args = parse_args()
    await run_targets(build_targets(args), args.timeout, args.retries)


if __name__ == "__main__":
    asyncio.run(main())
