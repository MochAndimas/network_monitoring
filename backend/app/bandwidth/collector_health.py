"""Collector readiness only; requires no database or third-party dependencies."""

import os
from pathlib import Path

from .spool import SpoolError, source_manifest


def collector_ready(directory: Path, router_id: int) -> bool:
    if type(router_id) is not int or router_id <= 0:
        return False
    try:
        # Never supply router_id here: health must not initialize a new stream.
        source = source_manifest(directory)
    except (OSError, SpoolError, ValueError, RecursionError):
        return False
    return source.router_id == router_id


def main() -> None:
    try:
        router_id = int(os.environ["BANDWIDTH_ROUTER_ID"])
    except (KeyError, ValueError):
        raise SystemExit(1) from None
    directory = Path(os.environ.get("BANDWIDTH_SPOOL_DIRECTORY", "/var/lib/bandwidth-spool"))
    raise SystemExit(0 if collector_ready(directory, router_id) else 1)


if __name__ == "__main__":
    main()
