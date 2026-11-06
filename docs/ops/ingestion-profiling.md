# Ingestion timing on the NAS

Run `sudo sh scripts/deploy-ingestion-profiling.sh` from the NAS project after
syncing the source. It sequentially builds and recreates only HO/RO ingestion
workers, preserving database, checkpoint/spool volumes, environment and policies.
Collectors and inventory remain running. Existing records resume from committed
offsets. It does not start a competing consumer or send Telegram messages.

Collect at least two profile summaries per worker:

```sh
sudo docker compose logs --since=5m flow-worker flow-worker-ro | grep flow_ingestion_profile
```

One summary is emitted at a completed/failed attempt boundary per 60 seconds,
not by a background heartbeat. A single long running attempt delays the summary.
The window is process-monotonic time, and includes time spent retrying/idle waiting.
Counters contain only router ID, call/error/idle counts, committed accepted and
rejected records, and accumulated phase milliseconds. No SQL, token, IP/MAC,
flow payload or message content is logged.

`total_ms` is the total time in attempts (including error recording on failure),
not window wall time. `segment_total_ms` is a parent of the parsing/identity/
insert/daily/flush phases; do not sum it with its children. `commit_ms` includes
transaction-exit work; `router_stream_lock_ms` includes session/connection
acquisition and the first lock. The second lock within segment ingestion is
`segment_lock_ms`. Failed attempts may have only completed phases; a large
unaccounted total can indicate a phase failed before its timing checkpoint.
Successful idle calls have no segment phases. Completed-checkpoint replay has
no new records. The profiler does not change commit/ack ordering or retries.

Use these summaries plus on-disk backlog/receipt lag to identify the dominant
cost before changing query semantics or increasing batch sizes. This is diagnostic
instrumentation, not a throughput fix or a claim the NAS backlog is resolved.
