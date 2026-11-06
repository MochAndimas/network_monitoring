# CPU investigation before Synology migration — 22 October 2026

## Observed causes

The local Docker engine reports 8 CPUs and approximately 3.825 GiB RAM.
The reported 900% historical spike was not captured during this investigation;
it cannot be attributed to one process with certainty. Startup and simultaneous
work can cause short spikes. The following recurring costs were reproduced.

1. Each printer scalar OID created a fresh PySNMP engine. Profiling one reachable
   printer showed 16 engines and about 1.59 of 2.26 CPU seconds in engine/MIB
   initialization. A NAS collection created 10 engines.
2. Two active printers answered ICMP but timed out over SNMP. The old collector
   still queried every base and toner OID, tried both protocol versions, and
   retried whole batches. Each failed collection created 64 engines and took
   approximately 95–96 seconds. Scheduler logs showed full device jobs taking
   116–122 seconds against a 60-second schedule, causing skipped executions.
3. Worker healthchecks start fresh Python interpreters. A profiled flow-worker
   healthcheck consumed 1.56 CPU seconds, including about 0.51 seconds compiling
   source. This is recurring overhead, separate from SNMP timeouts.

A sampled main-router spool contained zero ready segments; this does not prove
there was no earlier backlog. RO collector template warnings appeared shortly
after startup. No link between those warnings and sustained CPU was established.

## Changes

- Share one SNMP engine across the OIDs of each scalar batch; keep the printer's
  existing request concurrency limit. Drain cancelled tasks before closing it.
- Probe required printer sysUpTime before optional OID fan-out. If both protocol
  attempts fail, retain the failure status and skip optional base/toner reads.
- Reuse the working protocol for the toner batch. Keep existing timeouts,
  retry settings, and monitoring schedules.
- Compile application bytecode in backend and collector images at build time.
  Runtime still uses PYTHONDONTWRITEBYTECODE and non-root users.

## Read-only measurements on actual devices

Measurements were made while monitoring continued. They are samples, not a
controlled throughput benchmark or a guarantee of total-stack CPU reduction.

| Probe | Before wall seconds | After wall seconds | Before CPU seconds | After CPU seconds | Engines before → after |
| --- | ---: | ---: | ---: | ---: | --- |
| Printer 30 (reachable, initial paired comparison) | 3.2893 | 0.5540 | 3.1943 | 0.3959 | 16 → 2 |
| Printer 32 (SNMP timeout) | 94.7370 | 37.3386 | 9.1413 | 1.5619 | 64 → 8 |
| Printer 39 (SNMP timeout) | 96.4779 | 37.2431 | 10.8162 | 1.3817 | 64 → 8 |
| NAS 38 (initial paired comparison) | 6.6514 | 4.9328 | 2.3877 | 0.7396 | 10 → 5 |

The final reachable-printer sample was 0.6714 wall / 0.4692 CPU seconds, still
with 2 engines. SNMP failure statuses stayed `timeout` on the failing devices;
metric names were preserved for these sampled devices. Optional values can now
be unavailable sooner when the mandatory sysUpTime check fails.

One optimized full read-only collection produced 222 metrics for 38 devices in
38.6296 wall seconds and 4.7892 CPU seconds. Four SNMP collections were healthy;
three timed out (two printers and one NAS). No benchmark metrics were saved and
no benchmark notifications were sent.

Bytecode import measurements in a disposable candidate container were noisy:
median CPU time 2.2675 seconds without application bytecode versus 2.0456 with
bytecode (three samples each). Do not extrapolate this to overall CPU usage.

## Validation and rollout

36 regression tests passed in an isolated container without networking, using an
in-memory SQLite database. Coverage includes bounded requests, shared-engine
cleanup on cancellation, protocol fallback, timeout fan-out suppression, metric
normalization, and existing monitoring/alert behavior. Ruff lint passed.

A targeted local scheduler image is based on the original scheduler image and
copies only the two SNMP modules, then compiles bytecode. Other workspace edits
and dependency updates are excluded from that local rollout. The NAS source
package includes the source changes and requires a rebuild on the NAS.

Outstanding: fix the SNMP connectivity/configuration of printer IDs 32 and 39
and NAS 38; the optimization preserves those failures rather than curing them.
Check collector template warnings if they continue after template reception.

## Local deployment verification

The targeted scheduler image was applied successfully. Its environment and
command were compared with the prior container before recreation. In an
eight-minute post-deployment log window, seven device cycles completed in
20.6327–22.9665 seconds, with zero skipped device jobs and zero container
restarts. The container remained running. This is the deployed scheduler result,
separate from the read-only benchmark above.

Final backend and flow-collector Docker builds succeeded locally (ARM64).
The Synology architecture/build environment has not been exercised yet.
Original image tag and local rollback override are retained under
`.local-verification/performance/`. Other running services were not recreated.
