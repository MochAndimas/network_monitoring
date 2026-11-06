# Reconciliation locking fix

Production evidence: an inventory reconciliation SELECT on bandwidth_flows held
tens of thousands of exclusive index/primary record locks while other transactions
waited. Ingestion recovered after stopping HO inventory. A LIMIT of 500 returned
rows did not bound the records scanned/locked by the correlated locking query.

The fix discovers eligible IDs using a nonlocking read before taking the router
mutex. Only those IDs are subsequently locked using MySQL FORCE INDEX (PRIMARY).
Current history is re-read under the router mutex with a locking read, so stale
discovery, concurrent reconciliation, ambiguous ownership and gaps cannot assign
the wrong client. This is required with MySQL REPEATABLE READ snapshots.
Daily byte transfers and flow assignment still commit/rollback atomically.
The discovery query can still scan historical rows, but does not hold the router
mutex or exclusive flow locks during discovery. This fix does not promise a fixed
query duration or complete historical ownership coverage.

No migrations, environment edits, data deletion or spool replacement are needed.
After syncing the source to the NAS, from the existing project directory run:

```sh
sudo sh scripts/deploy-reconciliation-fix.sh
```

Only inventory HO/RO is stopped, rebuilt and recreated. Existing collectors,
ingestion workers, scheduler and database remain running; inventory snapshots
pause during the build. If build fails, inventory remains stopped for safety.

After startup, verify snapshot commits, both ingestion diagnostics, collector
restart counts and the actual ready-file backlog at several times. Ingestion
should advance toward current receipt times without recurring database_error.
Database pending_segments does not count every waiting file on disk. Keep old
spool data for the ingestion workers; do not clear it to hide lag.
