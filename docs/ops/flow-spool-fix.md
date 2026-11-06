# Collector capacity and NAS deployment

NAS observed about 250 small ready files, roughly 6 MB total, while worker
consumption continued. The default file-count bound is 256, independently of
the 256 MiB byte bound. This is consistent with file-count pressure, although
the former generic collector log did not retain the exact exception code.

Changes:

- Publish timed segments every five seconds instead of every second. The
  4 MiB segment size cap still applies. This reduces small-file transaction
  overhead at low/moderate rates; it does not promise fivefold record throughput.
- At capacity the collector seals its current file for consumption and waits
  before retrying only the unwritten payload. It preserves the same decoder
  process and IPFIX template cache instead of restarting on `spool_full`.
- The consumer chooses the oldest file modification time before its random
  UUID. Existing unfinished database checkpoints still take priority.
- Collector errors now retain safe spool error codes, never raw flow payloads.

The byte/file limits, checksums, commit-before-acknowledgement, stream identity
and policy binding remain enforced. No spool or database records are deleted
by deployment. Worker acknowledgement still removes successfully committed
segments as before. Waiting applies pipe backpressure: UDP can still drop if
sustained input exceeds processing capacity. Completeness remains unverified
until measured with a controlled transfer. Templates may need refreshing after
deployment restarts a decoder; repeated restart loops should cease.

Wait until Synology Drive reports the source update synced, or extract the
provided source-only fix archive into the NAS project. It contains no `.env`,
credentials, policies or database files. From the NAS project run:

```sh
sudo sh scripts/deploy-flow-spool-fix.sh
```

Only the HO/RO collectors and ingestion workers are rebuilt/recreated. Existing
inventory services, scheduler configuration, frontend and database are retained.
This starts the previously stopped RO collector again.

After startup, inspect both worker diagnostics and actual spool counts. The DB
`pending_segments` counter only counts registered incomplete checkpoints; it
does not count every ready file waiting on disk. Record collector restart counts
and backlog at two or more times several minutes apart with live Traffic Flow.
If backlog grows continuously, measure DB throughput/locks and flow rates before
increasing limits or enabling more workloads. Do not delete volume data to fix it.
