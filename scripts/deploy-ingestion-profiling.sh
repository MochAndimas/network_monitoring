#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
test -f backend/app/bandwidth/profiling.py
grep -q 'IngestionProfiler' backend/app/bandwidth/ingestion_runtime.py
docker compose config --quiet
# Sequential builds avoid the earlier NAS parallel-build timeout.
docker compose build flow-worker
docker compose build flow-worker-ro
docker compose up -d --no-deps --force-recreate flow-worker flow-worker-ro
docker compose ps flow-worker flow-worker-ro
echo 'After 2-3 minutes: docker compose logs --since=3m flow-worker flow-worker-ro | grep flow_ingestion_profile'
