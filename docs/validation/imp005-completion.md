# IMP-005 — Validasi penutupan

Tanggal validasi akhir: 30 September 2026. Source berada di working tree; laporan
ini tidak mengklaim commit/merge atau run GitHub Actions baru.

| Pemeriksaan | Hasil |
| --- | --- |
| `make backend-check` | Lulus; pip check, Ruff lint/format, mypy 213 file, pyright 0 error |
| Test backend | 327 passed; 18 MySQL dilewati pada database SQLite |
| Test MySQL 8.4 terpisah | 18 passed, termasuk worker/evaluator bersamaan |
| Alembic upgrade + check | Revisi 0030; tidak ada schema drift |
| Downgrade/upgrade 0030 | Lulus pada fixture, 23 September |
| Bandit | Lulus |
| `git diff --check` | Bersih |
| Compose profile notifications | Konfigurasi valid |
| Image backend | Build `network-monitoring-imp005-fixture:latest` berhasil |

Test mencakup commit/rollback, kebijakan grace/flap/cooldown/reminder/summary,
perubahan site/tujuan, alert pengganti, multipart tanpa acknowledgement prematur,
301 referensi pada satu event, cursor saat retry/redrive, retention, heartbeat,
SIGTERM/SIGINT, dan SIGKILL subprocess lalu pemulihan melalui proses baru.

Satu warning deprecation dependency Starlette/httpx masih muncul. Test MySQL memakai
container `imp005-mysql` port loopback 13316 dan database sintetis `imp005`;
pengujian tidak memakai database monitoring operasional atau transport Telegram.

[Benchmark 10.000 job](imp005-outbox-benchmark.json) direkam pada 23 September 2026.
[Runbook worker](../ops/notification-worker.md) menjelaskan migrasi, aktivasi profile,
health, redrive, retention, dan batas at-least-once. Image berhasil dibangun, tetapi
pengiriman Telegram live dan migrasi database operasional tidak diaktifkan di sini.
