# Synthetic insert-size comparison, 4 November 2026

Dedicated disposable local MySQL 8.4, real project flow schema/indexes/FKs,
2000 synthetic rows per transaction, one warm-up and five shuffled rounds per
size. Every size commits once; no production tables/credentials were used.
62,000 rows verified after all transactions including warm-up.

| Application chunk size | Median insert ms | Median commit ms | Median total ms |
| --- | ---: | ---: | ---: |
| Current bulk (0) | 198.976 | 6.699 | 205.675 |
| 50 | 225.180 | 6.187 | 231.367 |
| 100 | 190.618 | 6.011 | 196.572 |
| 250 | 195.277 | 8.167 | 203.563 |
| 500 | 182.774 | 5.948 | 188.722 |
| 1000 | 198.832 | 8.590 | 207.422 |

Median columns are independent statistics and need not sum. Application execute
calls are not counts of wire statements: the MySQL driver can split executemany.
Local host scheduling and cache effects remain; this is not a randomized NAS
storage benchmark. Dataset uses unresolved synthetic clients and a small growing
flow table, unlike the millions of production rows and competing NAS jobs.

Chunk 500 was about 8% faster in this run; chunk 50 was about 12% slower. These
results do not explain seconds of NAS commit/insert/directory-fsync latency and
do not justify promising backlog recovery from chunk-size changes. The running
production bulk path is unchanged (helper default zero); no NAS deployment was
performed. Next production investigation should measure storage sync latency
and competing I/O, not repeatedly enlarge transactions or disable durability.

`scripts/benchmark_flow_inserts.py` reproduces this comparison only when
BANDWIDTH_BENCHMARK_DATABASE_URL selects an empty mysql+aiomysql database with
a name ending in `_test`. It refuses existing tables, prints timings/counts
only, and never prints connection errors/URLs or credentials. It creates the
complete project schema in that dedicated database. Do not point it at production.
