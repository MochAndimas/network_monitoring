# Bounded reconciliation scan

The first lock fix removed the locking discovery SELECT, but its correlated
history filter could still run for minutes. This update removes that correlated
query entirely from discovery.

Each discovery scans a primary-key numeric window of at most 5,000 IDs, forced
to PRIMARY on MySQL, and returns at most 500 unresolved candidates. Ownership
history is checked only for that bounded set. Empty/unresolvable windows advance
the cursor rather than repeatedly searching the same old prefix. Up to ten
short transactions run per inventory poll; live ingestion can obtain the router
mutex between batches. There is no global reconciliation query over all flows.

A pass freezes its global high-water ID so continuously arriving traffic cannot
prevent wraparound. At its end, scanning returns to zero: old unresolved rows
can acquire delayed evidence during a later pass. Ambiguous/gapped evidence
remains unresolved. Cursor state is kept in the inventory process across polls;
the worker publishes the next cursor only after transaction commit. On restart
it safely starts a new bounded pass from zero. No schema migration is required.
Large histories may therefore take multiple passes/polls to reconcile; no
permanent skip or unbounded transaction is used to accelerate catch-up.

Current history is rechecked under the router lock using current locking reads,
and assignments/daily byte transfers remain atomic. Limits are logical bounds,
not promises that a query cannot wait on unrelated database locks or storage I/O.

After source sync (or extracting the source-only update into the NAS project):

```sh
sudo sh scripts/deploy-reconciliation-cursor-fix.sh
```

Only inventory HO/RO is stopped, rebuilt and restarted. Existing collectors,
ingestion workers, spool volumes, database, policies and .env remain in place.
Build failure leaves inventories stopped; ingestion remains available.

Compare multiple samples of actual .ready file counts and diagnostic receipt
lag with live traffic. Healthy alone is insufficient. If the backlog remains
full, investigate remaining ingestion/DB throughput rather than deleting spool
data, increasing capacity blindly or claiming the queue has drained. IPFIX
template decoding errors require a separate router/decoder investigation.
