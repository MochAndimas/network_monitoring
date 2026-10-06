# IMP-006 — Bounded rolling alert history

Validated on 1 October 2026. Implementation and local validation are complete.
Container deployment and a new remote CI run are not part of this validation.

## Contract studied and retained

Rolling rules use the newest **five samples**, ordered by `checked_at DESC, id
DESC`, rather than a fixed wall-clock interval. Numeric/status thresholds require
three matches; fewer than three total samples retain the existing immediate
trigger behavior. Baselines skip the newest sample and require at least three
numeric predecessors. Invalid numeric samples retain their existing treatment.
DNS/HTTP debounce requires two numeric samples; printer reboot detection compares
two uptime samples. Reachability recovery requires three newest successful ping
samples, including when the latest snapshot is absent.

A collection outage or sparse sampling may make this sample window span days.
An arbitrary time cutoff could discard nonmatching samples and cause an alert to
fire through the insufficient-samples fallback. This improvement deliberately
retains sample-based windows, static stale-snapshot behavior and future-dated
sample ordering. Dynamic snapshots still expire at the existing stale boundary
(`checked_at <= now - stale_after_seconds`) before history loading. Changing
static freshness or rolling-rule semantics requires a separate product decision.

## Implementation

`metrics/alert_history.py` builds bounded index seeks. Each exact device/name pair
selects at most five IDs (two for printer/DNS/HTTP) before combining branches with
`UNION ALL`. Only those IDs are fetched as ORM objects and sorted. The repository
deduplicates pairs and splits queries into at most 64 branches, so SQL size,
parameter count and returned rows are bounded per batch. History storage size
does not determine the number of samples visited per pair.

The engine batches rolling history by exact pairs and DNS/HTTP history together.
Dynamic interface names are queried only for their owning candidate device;
core ping/packet-loss/jitter pairs remain for all candidates, preserving recovery
without a snapshot. The old single-name repository method delegates to the new
method and retains its return shape. Rule evaluators and lifecycle behavior are
unchanged. No settings, dependency, index, or schema migration was added.

MySQL 8.4 `EXPLAIN ANALYZE` shows reverse covering index lookups through the
existing `ix_metrics_history_lookup`; each branch reports `Limit: 5` and **actual
rows=5**, even when the pair has 1,000 stored rows. InnoDB's implicit primary-key
suffix supplies the ID ordering; the explicit with-ID index also already exists.
The final sort handles only 320 selected rows for a 64-pair batch.

## Benchmark and acceptance

A disposable MySQL 8.4 container on loopback port 13326 was migrated from empty
to revision 0030. No application database, scheduler, collector or Telegram sender
was used. The workload contains 100 devices (10 internet targets, 90 Mikrotik),
500 pairs, including 180 unique dynamic interface names. Both the original
name-by-name ranking and new repository run the actual `_expected_alert_map`
orchestration and domain evaluators. Comparison includes all alert payload
fields except the independently generated `created_at` timestamp.

| Metric | 5,000 rows: original | 5,000 rows: bounded | 500,000 rows: original | 500,000 rows: bounded |
| --- | ---: | ---: | ---: | ---: |
| Queries per evaluation | 185 | 9 | 185 | 9 |
| Rows examined | 9,882 | 7,322 | 504,882 | 7,322 |
| Median evaluation time (3 runs) | 669.29 ms | 160.68 ms | 2,081.38 ms | 202.17 ms |
| Expected alert count | 200 | 200 | 200 | 200 |

All decisions matched. Rows examined come from the fixture connection's
`performance_schema.events_statements_summary_by_thread_by_event_name` counter;
the small, constant measurement-query overhead is included for both paths.
Raw timings include a 9.59-second first baseline run on the larger dataset; the
JSON retains every run, rather than dropping it. Local timings vary with cache,
hardware and concurrent work and do not establish production capacity.

For this fixed workload, the repeatable script enforces <=10 read queries,
<=10,000 examined rows, median <=1,000 ms and <=5% examined-row growth when the
history grows 100-fold. All budgets pass. Cost still grows with candidate pairs;
there is no claim of unlimited device or interface capacity.

Raw evidence: [imp006-rolling-benchmark.json](imp006-rolling-benchmark.json).
To repeat, create an empty disposable MySQL database ending in `_rolling_fixture`,
then run with an explicit fixture URL (never use application credentials):

```sh
APP_ENV_FILE='' DATABASE_URL='<fixture-mysql-pymysql-url>' .venv/bin/alembic upgrade head
APP_ENV_FILE='' DATABASE_URL='<fixture-mysql-pymysql-url>' .venv/bin/python -m scripts.benchmark_rolling_alert_history > /tmp/imp006-report.json
```

The script refuses other database names and nonempty device/metric tables. It
leaves synthetic rows for inspection; remove the disposable container afterward.

## Regression and quality gates

- 29 focused regression tests: exact pairs, duplicate inputs, missing history,
  64-pair batch boundary, out-of-order/tied/future timestamps, sample five versus
  sample six, insufficient/invalid samples, 30-day gaps, dynamic stale boundaries,
  reachability recovery without a snapshot, quality/anomaly, internet and printer
  rules.
- MySQL integration: 19 passed, including a new 70-pair, tied/sparse-history test
  comparing IDs and order against the original ranking query.
- `make backend-check`: 356 passed / 19 MySQL skipped; dependency consistency,
  Ruff lint/format, mypy (216 files), and Pyright (0 errors/0 warnings) passed.
  Bandit and whitespace validation passed. One Starlette/httpx dependency
  deprecation warning remains. The 19 MySQL tests passed separately.

The benchmark and MySQL regression use isolated fixtures. Backend tests use
SQLite and synthetic senders; this work sends no operational notifications.

The disposable container was stopped and auto-removed after validation.
