#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
grep -q 'def acknowledge_segments' backend/app/bandwidth/ingestion_runtime.py
grep -q 'max_segments=4' backend/app/bandwidth/ingestion_runtime.py
docker compose config --quiet
# Build sequentially while the old workers continue processing.
docker compose build flow-worker
docker compose build flow-worker-ro
docker compose up -d --no-deps --force-recreate flow-worker flow-worker-ro
docker compose ps flow-worker flow-worker-ro
echo 'After 3 minutes: docker compose logs --since=3m flow-worker flow-worker-ro | grep flow_ingestion_profile'
