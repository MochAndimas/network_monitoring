# Worker notifikasi Telegram

Scheduler dan siklus manual memakai `evaluate_operational_alerts`: perubahan alert,
incident, dan job outbox committed bersama. Tidak ada request Telegram pada jalur
tersebut. Tanpa chat ID, pemilihan notifikasi dinonaktifkan; dengan chat ID numerik,
job disimpan meskipun worker sedang berhenti. Jangan gunakan username `@...` yang
bisa berpindah kepemilikan sebagai tujuan persisten.

## Deploy

1. Hentikan scheduler dan akses siklus manual selama upgrade. Worker lama juga harus
   berhenti. Pastikan seluruh container memakai image source yang sama.
2. Jalankan `docker compose --profile ops run --rm migrate` untuk mencapai revisi
   `20260923_0030`. Jangan menjalankan source baru pada schema lama.
3. Konfigurasikan `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID` numerik.
4. Jalankan `docker compose up -d --build`. Worker ikut startup biasa.
   Dengan token/chat ID yang benar, pekerjaan yang masih antre dapat langsung
   terkirim ke Telegram. Untuk development/test tanpa pengiriman, gunakan environment
   terpisah dengan token/chat ID kosong dan database fixture.
5. Periksa health container dan `/observability/summary`: `notification_workers_alive`
   harus positif. Backlog kosong saja tidak membuktikan worker hidup.

CLI tanpa Docker: `python -m backend.app.notifications.worker`.
CLI health: `python -m backend.app.notifications.worker health` (hostname proses
harus sama dengan worker, misalnya melalui `docker compose exec notification-worker`).
Worker menjalankan dua lane, poll 1 detik, backoff runner 5 detik, lease 60 detik,
timeout per bagian 20 detik, maksimal 5 percobaan, retry eksponensial 5–300 detik.
Policy service bisa diinjeksi untuk deployment khusus/test; default operasional
berada pada dataclass policy, tidak diduplikasi di CLI.

## Kegagalan dan pemulihan

- SIGTERM/SIGINT menghentikan klaim baru dan memberi waktu 25 detik untuk pekerjaan
  berjalan. Compose memberi 35 detik sebelum SIGKILL. Lease yang ditinggalkan
  dapat diambil lagi sesudah 60 detik. Heartbeat tersimpan setiap 10 detik dan
  dianggap stale sesudah 45 detik. Proses/API tidak berbagi state memori.
- Job `dead` menahan stream agar RESOLVED tidak mendahului ACTIVE. Stream lain
  tetap berjalan. Periksa penyebab transport/konfigurasi, lalu jalankan:
  `docker compose run --rm notification-worker redrive --job-id 123`.
  Redrive hanya berlaku untuk dead, mengulang attempt counter dan mempertahankan
  tujuan, isi, urutan, serta cursor. Job sent tidak dapat di-redrive.
- Jangan mengubah tujuan job yang sudah memiliki snapshot. RESOLVED menggunakan
  stream dan tujuan ACTIVE terdahulu, termasuk ketika site/chat konfigurasi berubah.
  Alert pengganti dikorelasikan dengan device/type dalam jendela konfigurasi.
- Job legacy tanpa destination ditolak transport operasional; tidak dialihkan ke
  chat konfigurasi terbaru. Rekonsiliasi asalnya dari catatan operator sebelum
  migrasi/aktivasi. Tidak ada command otomatis yang menebak penerima historis.
- Pesan panjang dibagi per 4096 unit UTF-16 tanpa kehilangan karakter. Satu event
  tetap satu job walaupun memiliki lebih dari 250 referensi. Cursor diperbarui
  setelah setiap bagian diterima; timestamp alert dan timeline incident baru
  diakui atomik setelah seluruh bagian lengkap. Retry melanjutkan cursor tersebut.
- Pengiriman bersifat **at-least-once**. Provider bisa menerima satu bagian sesaat
  sebelum proses mati atau penyimpanan cursor gagal. Bagian itu dapat terkirim
  ulang. Tidak ada jaminan exactly-once dari Telegram.

## Retention dan observability

Worker membersihkan paling banyak 250 job sent tiap 360 heartbeat (sekitar satu jam).
Hanya job berumur 30 hari yang memenuhi syarat. Seluruh stream dengan pekerjaan
belum selesai, alert aktif, dan korelasi alert yang baru resolved tetap dipertahankan.
Pending/processing/dead tidak dihapus otomatis. Referensi ikut dihapus; row koordinasi
stream dipertahankan untuk menjaga koordinasi producer. Heartbeat lebih tua dari
30 hari dibersihkan. Retention alert/incident sendiri tetap diatur kebijakan domain.

API summary memuat hitungan/umur outbox dan jumlah worker hidup. Prometheus memuat
`network_monitoring_notification_workers_alive` serta gauge outbox yang sudah ada.
Gauge berasal dari database bersama; gunakan `max` lintas replica API, bukan `sum`.
Jangan menaruh payload, chat ID, atau token pada label. Worker tidak mencatat isi
exception transport karena URL provider dapat mengandung token.

## Verifikasi tanpa mengirim Telegram

- `pytest -q`: rollback/commit, grace/flap/cooldown/reminder/summary, grouping,
  perubahan route, alert pengganti, multipart/retry/redrive/retention, signal dan
  subprocess kill/restart memakai sender fixture.
- Test MySQL `test_mysql_evaluator_and_delivery_ack_share_domain_first_lock_order`
  menjalankan lifecycle worker bersamaan dengan evaluator yang memegang lock alert.
- Benchmark: buat database MySQL kosong dengan nama berakhiran `_outbox_fixture`,
  migrasikan, lalu jalankan `python -m scripts.benchmark_notification_outbox` dengan
  `APP_ENV_FILE=''` dan `DATABASE_URL` fixture tersebut. Script menolak database
  dengan nama lain atau tabel alert/outbox yang berisi data. Sender sepenuhnya lokal.
- Hasil lokal 23 September 2026 tersimpan pada
  `docs/validation/imp005-outbox-benchmark.json`: 10.000 job, 100 stream, 20 scrape
  paralel; adapter 1.000 event/100 site menjadi 100 job dalam 1,35 detik. Scrape serial
  p95 16,27 ms; paralel bersama worker p95 188,97 ms. Dua lane menyelesaikan 20 job
  dalam 1,07 detik tanpa error/lease lost. EXPLAIN memakai indeks due pada kandidat
  dan indeks stream pada predecessor; agregat health memakai range indeks due.
  Ini workload sintetis MySQL 8.4 di Docker lokal, bukan kapasitas produksi maksimum.
  Ukur ulang setelah perubahan distribusi backlog atau hardware; query discovery
  masih membaca kandidat eligible sebelum membatasi 32 hasil.
