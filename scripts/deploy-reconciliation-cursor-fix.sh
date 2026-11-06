#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
grep -q 'class ReconciliationCursor' backend/app/services/bandwidth_reconciliation_service.py
grep -q 'window_end = min(scan.after_id + 5000' backend/app/services/bandwidth_reconciliation_service.py
grep -q 'reconciliation_cursor=reconciliation_cursor' backend/app/bandwidth/inventory_worker.py
docker compose config --quiet
docker compose stop flow-inventory flow-inventory-ro
docker compose build flow-inventory flow-inventory-ro
docker compose up -d --no-deps --force-recreate flow-inventory flow-inventory-ro
docker compose ps flow-inventory flow-inventory-ro
echo 'Check snapshot commits, flow receipt lag and ready-file counts across several live samples.'
