#!/bin/sh
# Run from the synced NAS project; does not modify environment, policy or volumes.
set -eu
cd "$(dirname "$0")/.."
grep -q 'wait_for_capacity=wait_for_capacity' backend/app/bandwidth/collector.py
grep -q 'def _write_available' backend/app/bandwidth/spool.py
docker compose config --quiet
# Build while the existing services remain available. A failed build stops here.
docker compose build flow-collector flow-collector-ro flow-worker flow-worker-ro
docker compose up -d --no-deps --force-recreate flow-collector flow-collector-ro flow-worker flow-worker-ro
docker compose ps flow-collector flow-collector-ro flow-worker flow-worker-ro
echo 'Deployment requested. Verify restart counts stay unchanged and spool backlog decreases under live traffic.'
