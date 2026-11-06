#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
grep -q 'FORCE INDEX (PRIMARY)' backend/app/services/bandwidth_reconciliation_service.py
grep -q 'candidate_ids' backend/app/services/bandwidth_reconciliation_service.py
docker compose config --quiet
# Release old reconciliation transactions; ingestion/collectors remain running.
docker compose stop flow-inventory flow-inventory-ro
docker compose build flow-inventory flow-inventory-ro
docker compose up -d --no-deps --force-recreate flow-inventory flow-inventory-ro
docker compose ps flow-inventory flow-inventory-ro
echo 'Verify inventory snapshots, worker diagnostics, database locks and on-disk spool backlog under live traffic.'
