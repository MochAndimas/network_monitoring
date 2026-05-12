"""Prepare the Prometheus multiprocess directory for container startup."""

from __future__ import annotations

import os
from pathlib import Path


TRUE_VALUES = {"1", "true", "yes", "on"}


def main() -> None:
    """Create the multiprocess directory and optionally remove stale metric shards."""
    raw_dir = str(os.getenv("PROMETHEUS_MULTIPROC_DIR") or "").strip()
    if not raw_dir:
        return

    multiproc_dir = Path(raw_dir)
    multiproc_dir.mkdir(parents=True, exist_ok=True)

    clean_on_startup = str(os.getenv("PROMETHEUS_MULTIPROC_CLEAN_ON_STARTUP") or "").strip().lower() in TRUE_VALUES
    if not clean_on_startup:
        return

    for metric_file in multiproc_dir.glob("*.db"):
        if metric_file.is_file():
            metric_file.unlink()


if __name__ == "__main__":
    main()
