"""Read-only status and controlled-transfer validation for operators.

Baseline files are private, exclusive and contain no credentials. This command
never changes router settings, commits DB writes or deletes spool data.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

from ..core.config import settings
from ..db.session import SessionLocal, engine
from ..services.bandwidth_validation_service import capture_baseline, ingestion_status, observe_transfer
from .ingestion_config import load_policy, strict_json
from .validation import TransferBaseline, compare_transfer


async def run(args: argparse.Namespace) -> tuple[dict, int]:
    policy = load_policy(Path(args.policy or settings.bandwidth_flow_policy_file))
    async with SessionLocal() as db:
        if args.command == "status":
            result = await ingestion_status(db, policy)
            return result, 0 if result["worker_alive"] else 1
        if args.command == "baseline":
            baseline = await capture_baseline(db, policy, args.device_ip)
            # Never overwrite a prior measurement window, even accidentally.
            descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as output:
                output.write(json.dumps(baseline.payload(), indent=2) + "\n")
                output.flush()
                os.fsync(output.fileno())
            return baseline.payload(), 0
        path = Path(args.baseline)
        if path.stat().st_size > 65536:
            raise ValueError("oversized_baseline")
        baseline = TransferBaseline.parse(strict_json(path.read_bytes()))
        observed = await observe_transfer(db, policy, baseline)
        expected = {
            key: value
            for key, value in {"upload": args.upload_bytes, "download": args.download_bytes}.items()
            if value is not None
        }
        result = compare_transfer(observed, expected, args.tolerance_bps)
        result.update(
            {
                "router_id": baseline.router_id,
                "device_ip": baseline.device_ip,
                "flow_count": observed["flow_count"],
                "flows_started_before_baseline": observed["flows_started_before_baseline"],
                "observed_upload_bytes": str(observed["upload"]),
                "observed_download_bytes": str(observed["download"]),
            }
        )
        return result, 0 if result["verdict"] == "within_tolerance" else 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", help="Policy path; defaults to BANDWIDTH_FLOW_POLICY_FILE")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    baseline = commands.add_parser("baseline")
    baseline.add_argument("--device-ip", required=True)
    baseline.add_argument("--output", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--baseline", required=True)
    verify.add_argument("--upload-bytes", type=int)
    verify.add_argument("--download-bytes", type=int)
    verify.add_argument("--tolerance-bps", type=int, default=500)
    args = parser.parse_args()

    async def execute() -> tuple[dict, int]:
        try:
            return await run(args)
        finally:
            await engine.dispose()

    try:
        result, code = asyncio.run(execute())
    except Exception:
        # SQL errors can contain connection/statement context; do not print them.
        result, code = {"error": "diagnostic_failed", "check": "policy_schema_database_and_baseline"}, 1
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
