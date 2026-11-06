# Grouped ingestion transactions and spool acknowledgement

NAS profiling showed seconds spent committing transactions and syncing spool
acknowledgement, while parsing and identity lookup used much less time. The
worker now processes up to four sealed segments in one transaction, instead of
one commit per segment. Durability settings on MySQL remain unchanged.

Limits per transaction:

- At most four segments in the running worker.
- At most min(batch_size * 4, 10000) records, accepted plus rejected. With the
  existing batch_size=500 this is 2000 records total. A partially consumed
  segment retains its checkpoint and must finish before the next segment.
- Ten-second soft work budget: after finishing a segment, do not start another
  if the budget has expired. It cannot interrupt an in-flight SQL call/commit.
- Sixteen MiB soft read budget across segments. A single legacy segment can
  exceed this up to the existing maximum segment size; no additional segment
  starts if it would exceed the group budget.

An existing incomplete DB checkpoint is processed first; the other candidates
are selected by oldest file mtime. The router mutex and one transaction protect
the complete group. If any read/ingestion fails before commit, the group rolls
back and all input files remain. No acknowledgement takes place inside the
transaction. After commit, only completed files are unlinked and the directory
is fsynced once for the group, including on a partial unlink failure. Checkpoints
allow safe replay if a crash leaves/resurrects committed files; records and daily
bytes must not be inserted twice. The original single-segment ingest_once API
default is retained for callers/tests; the continuous worker requests four.

Tests verify one commit and one directory sync for four segments, rollback of
an entire group, partial post-commit acknowledgement replay, record/time bounds,
existing retry/checksum invariants, identity reconciliation and daily totals.
Grouping reduces fixed sync count when multiple small segments fit the limits;
it does not guarantee a particular NAS throughput or eliminate UDP packet loss.

After source sync or extracting the source-only update into the NAS project:

```sh
sudo sh scripts/deploy-grouped-ingestion.sh
```

Only the HO/RO ingestion workers are built/recreated; database, policies, .env,
spool volumes, inventory and collectors remain in place. Existing persisted
spool data resumes from its committed checkpoints. Collect several one-minute
flow_ingestion_profile summaries and compare accepted records/second, commit
and acknowledge milliseconds/record, actual ready-file backlog and receipt lag
under live traffic. Raw per-call timings are not directly comparable because
each call can now handle multiple segments. segment_total_ms overlaps its child
phases and must not be summed with them. Pending DB segments are not a count of
all ready files on disk. Do not delete backlog or weaken fsync settings to hide lag.
