# IMP-009 — retention dengan transaksi terbatas

Status: Done untuk implementasi, pengujian dan penerapan lokal, 1 Oktober 2026.

## Perubahan dan kontrak

Alur lama men-stream seluruh agregasi dan men-delete seluruh raw kedaluwarsa sebelum
satu commit akhir. Alur baru membatasi ID sumber per batch, menggabungkan agregat
dengan checkpoint secara atomik, lalu commit setiap batch pada jalur scheduler.
Delete raw hanya memilih ID yang sudah terwakili di rollup dan archive yang masih
ada; latest snapshot tetap dilindungi. Batas jumlah batch per fase mencegah satu
run menghabiskan backlog tanpa batas. Run berikutnya melanjutkan dari checkpoint.

Repository retention menangani seleksi/locking dan syarat delete. Service mengatur
fase serta budget. Modul agregasi menangani perhitungan/merge dan checkpoint.
Helper delete bersama dipakai monitoring dan auth agar cleanup scheduler tidak
menyisakan delete auth tanpa batas. Summary memakai pagination grup per hari,
checkpoint offset yang persisten, bootstrap terbatas, serta rotasi hari selesai
untuk merekonsiliasi metadata perangkat. Tidak ada migrasi atau dependency baru.

Metrik terlambat memakai ID baru pada bucket timestamp lama; aggregate count,
numeric weighted average, min/max dan last value digabung sekali, termasuk setelah
raw lama sebagian dipangkas. Raw bersifat append-only melalui repository. Fingerprint
legacy/null atau aggregate yang hilang menghentikan pruning; perubahan SQL arbitrer
pada sumber/checkpoint tidak didukung dan tidak semuanya dapat dideteksi otomatis.
Pemulihan memerlukan backup konsisten atau sumber lengkap, bukan hanya raw tersisa.

[Kontrak operasional, konfigurasi, retry dan pemulihan](../ops/retention.md)
menjelaskan batas serta mode caller-owned `commit=False`. Mode tersebut tetap atomik
milik caller; scheduler memakai jalur commit per batch.

## Bukti pengujian

- `make backend-check`: 381 passed, 22 MySQL tests skipped; dependency check, Ruff,
  formatting, mypy (226 source files) dan Pyright lulus. Bandit backend/shared/scripts
  juga lulus. Satu warning deprecation Starlette/httpx yang sudah ada tetap muncul.
- MySQL 8.4.11 fixture yang dimigrasikan: 22 tes integrasi lulus. Tes baru membuktikan
  budget per run/resume dan retention menunggu writer perangkat, lalu melihat ID lebih
  kecil yang baru commit walaupun ID global lebih besar sudah commit pada perangkat lain.
- Tes retention baru mencakup kegagalan setelah write sebelum commit pada rollup,
  archive, delete dan summary; batch terdahulu bertahan dan retry tidak menggandakan
  sampel. Juga diuji backlog lintas run, caller-owned rollback, delete sebelum archive,
  aggregate hilang, fingerprint legacy, late arrival/timestamp tie, pagination summary,
  perubahan site, batas delete telemetry/alert/incident dan perlindungan alert aktif.
- Tes scheduler aktual memastikan guard cleanup dipegang selama fase monitoring/auth,
  lock ditolak menghentikan pekerjaan, dan scheduler tidak memakai commit akhir tunggal.
- Schema drift fixture: `alembic check` menghasilkan “No new upgrade operations detected.”

## Benchmark backlog

Bukti mentah: [imp009-retention-benchmark.json](imp009-retention-benchmark.json).
Script reproduksi: `scripts/benchmark_retention.py`, hanya pada fixture kosong
`*_retention_fixture` dengan dotenv lokal dimatikan.

100 perangkat × 1.000 metrik = 100.000 raw kedaluwarsa pada satu hari WIB; satu seri
ping per perangkat, 100 referensi latest. Source batch 250, delete batch 500,
50 batch per fase. Delapan run memproses backlog dan run kesembilan memverifikasi
idempotensi. Seluruh 100.000 sampel tercatat di rollup serta archive, rata-rata
archive 499,5 dan tepat 100 raw latest tersisa.

1.083 transaksi dan 7.527 statement SQL terukur: median transaksi 37,51 ms,
p95 73,13 ms, maksimum 295,61 ms. Sumber maksimal 250 ID dan delete maksimal
500 ID. Total sembilan run 47.706,08 ms; run terlama 6.675,12 ms. Gate integritas,
batas ID dan maksimum 2.000 ms/transaksi lulus. Run pertama alat ukur sempat
menghitung parameter filter sebagai ID delete; penghitung diperbaiki dan hasil di
atas diulang dari database fixture kosong.

Angka ini hasil fixture lokal, bukan batas waktu mutlak atau sertifikasi kapasitas
produksi. Budget membatasi ID yang diagregasi/dimutasi; discovery dan query summary
masih dapat memeriksa lebih banyak baris indeks. Tidak ada perbandingan throughput
langsung terhadap implementasi lama. Lebar payload, banyak seri, metadata churn,
lock wait dan perangkat dalam satu summary group memerlukan pengukuran tersendiri.

## Penerapan lokal

Backend dan scheduler telah direbuild melalui `docker compose up -d --build backend
scheduler`. Readiness backend melaporkan ready, database/scheduler up. Proses scheduler
aktif dan job normal kembali berhasil; konfigurasi source/delete/max-batches yang
terpasang adalah 1.000/1.000/100. Tidak memanggil cleanup manual pada database
operasional; job retention versi baru berjalan pada jadwal berikutnya (default 24 jam).
Fixture MySQL telah dihentikan/auto-remove. Tidak ada run CI remote atau deployment
lingkungan lain; tidak membuat commit/PR pada tahap ini.
