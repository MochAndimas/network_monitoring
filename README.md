# Network Monitoring

Network Monitoring adalah aplikasi observabilitas jaringan dengan backend FastAPI, scheduler/collector Python, MySQL, dan dashboard Next.js.

## Komponen

- `frontend/` — dashboard Next.js pada `http://localhost:3000`.
- `backend/` — API FastAPI pada `http://localhost:8000`.
- `scripts/` — bootstrap, migrasi, dan utilitas operasional.
- `alembic/` — migrasi database.

## Menjalankan lokal

Siapkan `.env` dari `.env.example`, lalu isi seluruh secret wajib, khususnya database, auth, bootstrap admin, CORS, dan trusted hosts.

Untuk deployment, set `FRONTEND_PUBLIC_API_URL` ke alamat API yang dapat diakses browser pengguna dan sesuaikan `CORS_ORIGINS`. Nilai ini dimasukkan ke bundle frontend saat build; perubahan nilainya memerlukan rebuild frontend (`docker compose up -d --build frontend`). Contoh: `FRONTEND_PUBLIC_API_URL=https://api.example.com`. Nilai ini bersifat publik dan tidak boleh berisi secret.

```sh
docker compose up -d --build
```

Layanan utama:

- Dashboard: `http://localhost:3000`
- API: `http://localhost:8000`

Untuk menjalankan frontend tanpa Docker:

```sh
cd frontend
corepack enable
pnpm install --frozen-lockfile
pnpm dev
```

Gunakan Node.js 22 dan versi pnpm pada `frontend/package.json`. Untuk API selain `http://localhost:8000`, buat `frontend/.env.local` berisi `NEXT_PUBLIC_API_URL=https://api.example.com` sebelum `pnpm dev` atau `pnpm build`. File `.env` di root digunakan Compose/backend; Next.js membaca file environment di direktori frontend.

Untuk setup backend lokal, gunakan Python 3.12 dengan virtual environment:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements/dev.txt
```

Schema produksi dikelola melalui Alembic. Pada database baru, jalankan `docker compose --profile ops run --rm migrate` sebelum layanan aplikasi dijalankan. `DATABASE_AUTO_CREATE_TABLES` hanya untuk environment development/fixture.

## Validasi

```sh
cd frontend
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

Validasi backend dari root dengan virtual environment aktif:

```sh
make lint
make typecheck
make test-fast
# Sertakan test slow; MySQL dilewati tanpa URL fixture MySQL:
make test
make precommit-run
```

`make backend-check` menjalankan `pip check`, lint dasar, lint aturan bertahap, pemeriksaan format tanpa menulis file, mypy, pyright, dan seluruh test backend. `make frontend-check` menjalankan lint, typecheck, unit test, dan build frontend. `make ci` menggabungkan kedua target tersebut; resep `just` meneruskan ke target Make yang sama. Istilah lint bertahap merujuk scope modul yang menerapkan aturan lebih ketat, bukan file pada Git staging area.

`make ci` adalah gate fungsional lokal. Pre-commit, migrasi/integrasi MySQL, smoke non-functional, audit dependency/SAST, secret-scan riwayat Git, serta build image Docker tetap gate terpisah di CI. Test MySQL dan operasi migrasi harus diarahkan ke database fixture terisolasi. `just` tidak memuat `.env` otomatis; aplikasi dan Compose tetap memakai mekanisme konfigurasi masing-masing. Environment yang diekspor secara eksplisit tetap berlaku, jadi jangan ekspor URL database operasional saat menjalankan pengujian.

Alat audit dipin bersama di `requirements/security.txt`, yang juga diimpor oleh dependency development. Jalankan `make security-dependencies`, `make security-bandit`, dan `make security-semgrep` untuk memeriksa masing-masing gate. CI tetap menjalankan SAST ketika audit dependency gagal agar semua temuan terlihat; kegagalan tetap menggagalkan job. Versi alat dipin, tetapi database advisory dan ruleset Semgrep remote tetap dapat berubah.

Setelah instalasi alat audit, jalankan `python -m pip check` dan `semgrep --version`; metadata dependency yang valid belum menjamin scanner dapat dimulai. Semgrep 1.89 masih membutuhkan `pkg_resources` melalui OpenTelemetry, sehingga setuptools dipin khusus di requirements alat audit. Hapus pin kompatibilitas ini saat upgrade Semgrep sudah lolos startup dan scan. Jika macOS melaporkan trust anchors tidak ditemukan, gunakan CA bundle yang valid, misalnya `SSL_CERT_FILE="$(python -m certifi)" make security-semgrep`; jangan menonaktifkan verifikasi TLS.

Untuk validasi checkout bersih, gunakan clone/worktree dari commit yang memuat seluruh source dan konfigurasi baru, pasang dependency pada virtual environment baru serta `pnpm install --frozen-lockfile`, lalu jalankan gate di atas tanpa menyalin `.env`, cache, atau dependency lokal. Salinan working tree yang menyertakan file untracked hanya membuktikan kandidat source bisa divalidasi; itu belum membuktikan checkout commit atau CI remote sudah lulus.

Progres perbaikan arsitektur dan quality gate dicatat dalam `IMPROVEMENTS.me`.

Secret-scan riwayat dapat dijalankan dengan `gitleaks git --redact --log-opts=--all .` dari repository dengan seluruh riwayat tersedia. `.gitleaksignore` hanya mengecualikan empat fingerprint contoh development pada README di satu commit historis (lihat tahap 1D4). Tidak ada pengecualian menyeluruh untuk README, API key, atau commit tersebut. Temuan baru tetap harus ditriase; jangan memasukkan kredensial nyata ke contoh dokumentasi. Scan Git tidak mencakup perubahan yang belum di-commit dan tidak menggantikan verifikasi CI remote.

Frontend mendeklarasikan `plotly.js` secara langsung karena wrapper `react-plotly.js` memuat `plotly.js/dist/plotly`. Versinya dipin agar implementasi grafik tidak bergantung pada resolusi peer otomatis. Bundle `plotly.js-dist-min` yang tidak diimpor sudah dihapus. Override PostCSS di `frontend/pnpm-workspace.yaml` dibatasi pada Next 15 untuk menutup advisory versi 8.4.31; hapus ketika upstream memakai versi patched, setelah lint/typecheck/test/build dan tampilan grafik/CSS diverifikasi. Jalankan `pnpm audit --prod` dari direktori frontend setelah perubahan dependency.

## Konfigurasi beberapa MikroTik

Collector mengumpulkan ping untuk semua device aktif bertipe `mikrotik` (atau nama yang memuat “Mikrotik”). Metrik RouterOS API hanya ditempelkan ke device yang `ip_address`-nya sama dengan host target. Setiap router karena itu harus terdaftar sebagai device aktif dengan IP yang persis sama.

Konfigurasi lama `MIKROTIK_HOST`, `MIKROTIK_PORT`, `MIKROTIK_USERNAME`, dan `MIKROTIK_PASSWORD` tetap menjadi target `primary`. Variabel kompatibilitas `RO_MIKROTIK_HOST`, `RO_MIKROTIK_PORT`, `RO_MIKROTIK_USERNAME`, dan `RO_MIKROTIK_PASSWORD` menambahkan target `regional-office`. Keduanya diteruskan ke backend dan scheduler oleh Compose.

Untuk tiga lokasi atau lebih, gunakan satu JSON `MIKROTIK_TARGETS` dengan nama target bebas:

```env
MIKROTIK_TARGETS={"head-office":{"host":"192.0.2.1","port":8728,"username":"monitor","password":"..."},"regional-office":{"host":"192.0.2.2","port":8728,"username":"monitor","password":"..."}}
```

Jika `MIKROTIK_TARGETS` terisi, nilainya menjadi sumber utama dan menggantikan target `MIKROTIK_*`/`RO_MIKROTIK_*`. Setiap entry wajib memiliki host, username, dan password; port harus 1–65535 dan host tidak boleh duplikat. File JSON rahasia dapat dipakai melalui `MIKROTIK_TARGETS_FILE` pada production.

Snapshot metrik lama dibaca berurutan karena satu database session tidak aman dipakai bersamaan. Setelah itu koneksi RouterOS untuk target yang cocok berjalan dengan concurrency yang dibatasi konfigurasi monitor. Kegagalan satu router menghasilkan `mikrotik_api` error untuk device tersebut tanpa menggagalkan hasil router lain. Setelah mengubah konfigurasi, rebuild/restart backend dan scheduler.

Lock monitoring dengan `wait=True` melempar `PipelineLockTimeoutError` jika batas `MONITORING_LOCK_TIMEOUT_SECONDS` tercapai; operasi terlindungi tidak dijalankan. Batas berlaku per scope pada MySQL maupun fallback proses lokal. Pemanggil `wait=False` wajib memeriksa hasil boolean. Timeout scheduler tercatat sebagai kegagalan job; transaksi metrik yang sudah committed sebelum timeout lock alert tetap tersimpan.

Ownership collector perangkat dipakai bersama oleh scheduler dan `/run-cycle`: pusat mengecualikan `COLLECTOR_AGENT_SITES`, sedangkan proses dengan `COLLECTOR_AGENT_SITE` hanya menjalankan collector perangkat untuk site tersebut. Collector internet/server/MikroTik tetap milik pusat. Nama site delegasi harus konsisten pada konfigurasi pusat dan agent.

Penulis metrik melalui repository mengunci baris perangkat sampai transaksi selesai. Pada MySQL, snapshot dibaca ulang dengan locking read; sampel lama tetap masuk history tetapi tidak mengganti snapshot terbaru. Urutan snapshot memakai `checked_at`, kemudian ID metrik. Lock row pada SQLite tidak memberikan koordinasi lintas proses setara MySQL.

Status scheduler memiliki identitas gabungan job dan owner (`central` atau site agent), interval yang dilaporkan worker, dan heartbeat masing-masing. System Health serta CSV menampilkan Agent / Site; gauge Prometheus scheduler menambahkan label `agent_id`. Identitas ini mewakili owner logis: dua proses untuk site yang sama berbagi identitas, bukan diperlakukan sebagai dua host berbeda.

Migration `20260908_0025` mempertahankan status lama sebagai `central`. Riwayat yang dahulu tercampur antar-agent tidak dapat direkonstruksi; status baru terpisah sejak worker versi baru berjalan. Hentikan worker lama, upgrade schema, lalu jalankan backend/scheduler/agent versi seragam. Downgrade ditolak selama row non-central masih ada untuk mencegah kehilangan riwayat; ekspor dan rekonsiliasi harus dilakukan secara eksplisit terlebih dahulu.

Perubahan namespace lock site memerlukan restart terkoordinasi backend/scheduler/agent dengan versi yang sama. Hindari menjalankan worker versi lama dan baru bersamaan; perubahan konfigurasi delegasi dilakukan setelah pekerjaan aktif selesai.

Pytest menonaktifkan pembacaan `.env` lokal agar hasil tidak bergantung pada konfigurasi operator. Environment proses yang diberikan secara eksplisit (misalnya `DATABASE_URL` untuk fixture MySQL CI) tetap berlaku. Pada perintah backend lain, set `APP_ENV_FILE` ke lokasi dotenv yang diinginkan, atau ke string kosong untuk menonaktifkan pembacaan dotenv; default tetap `.env`.

E2E memakai Playwright dan hanya boleh dijalankan pada environment fixture dengan kredensial test. Lihat `frontend/e2e/README.md`.

## Keamanan

- Jangan menyimpan secret di repository.
- Batasi `CORS_ORIGINS` ke origin dashboard yang digunakan.
- Jalankan mutation E2E hanya pada fixture terisolasi.

## Fondasi outbox notifikasi

Untuk proses worker khusus, `run_notification_process(worker)` menyediakan stop event yang dipicu SIGTERM/SIGINT. Callback `worker(stop)` dapat membungkus `run_alert_notification_worker`; pemanggil tetap memiliki `asyncio.run()`, konfigurasi transport/session, dan disposal engine dalam `finally`. Adapter harus dijalankan pada main thread proses khusus, bukan di dalam server API yang sudah memiliki signal handler. Handler sebelumnya dipulihkan saat selesai, gagal, atau dibatalkan. Signal berulang tidak memperpanjang grace deadline. SIGKILL tidak dapat menjalankan cleanup; pemulihan tetap bergantung pada lease. Adapter ini belum menjadi CLI atau service Compose yang aktif.

`GET /observability/summary` (admin) memuat `notification_outbox`: jumlah job Telegram pending/processing/dead, pending yang sudah jatuh tempo, lease processing yang kedaluwarsa, dan umur job tertua per status sejak dibuat. Nilai kosong adalah nol; umur negatif akibat selisih jam dibatasi nol. Pending jatuh tempo masih dapat tertahan oleh job sebelumnya dalam stream, sehingga bukan jumlah job yang pasti dapat diklaim. Antrean kosong tidak membuktikan worker aktif.

`GET /observability/metrics` mengekspor gauge `network_monitoring_notification_outbox_jobs`, `network_monitoring_notification_outbox_oldest_age_seconds`, `network_monitoring_notification_outbox_due_pending`, dan `network_monitoring_notification_outbox_expired_leases`. Label tetap hanya channel Telegram dan status yang relevan; pesan, tujuan, stream, dan ID job tidak diekspos. Nilai berasal dari snapshot database bersama: jangan menjumlahkan hasil scrape beberapa replika API untuk menghitung backlog; agregasikan dengan `max` per label antrean bila perlu. Setiap request observability menambah satu query agregat atas job belum selesai, tanpa membaca payload atau mengunci row. Biaya query tetap mengikuti ukuran backlog; benchmark MySQL dan retention masih diperlukan.

Service `run_alert_notification_worker` menyediakan polling dengan concurrency terbatas, error backoff, dan graceful shutdown melalui `asyncio.Event` yang diinjeksi pemanggil. `NotificationWorkerPolicy` mengatur concurrency (default 2), polling (1 detik), backoff (5 detik), dan grace shutdown (25 detik). Pemanggil memiliki database engine, transport, dan signal handler; runner belum didaftarkan pada proses operasional. Report hasil hanya menghitung satu run, bukan metrik backlog. Cancellation membiarkan lease dipulihkan pada delivery berikutnya; pesan dapat terkirim ulang jika provider sudah menerima sebelum acknowledgement tersimpan.

Migration `20260908_0026` menyediakan antrean persisten untuk tahap integrasi notifikasi berikutnya. Repository enqueue mengikuti transaksi pemanggil; service `deliver_one` melakukan pengiriman di luar session database, dengan lease, retry, dan acknowledgement bertoken.

Migration `20260908_0027` menambahkan referensi alert/action untuk setiap job. `enqueue_alert_notification` menyimpan referensi dalam transaksi pemanggil tanpa menandai alert terkirim. `deliver_alert_notification` mengikat acknowledgement outbox, timestamp Telegram alert, dan timeline incident dalam satu transaksi setelah sender berhasil. Kegagalan pembaruan domain membatalkan seluruh acknowledgement; lease kemudian dapat dipulihkan. Referensi historis tetap disimpan ketika retention menghapus alert, tanpa membuat ulang alert tersebut.

Fondasi ini belum terhubung ke engine alert atau scheduler produksi. Detail batas tahap 3B dan checklist aktivasi tahap 3C berada di `IMPROVEMENTS.me`. Pengiriman eksternal bersifat at-least-once: crash setelah provider menerima pesan sebelum acknowledgement dapat menyebabkan duplikasi. Job dead menahan stream hingga rekonsiliasi eksplisit.

Kebijakan pemilihan event Telegram berada di `backend/app/alerting/engine_parts/notification_policy.py`; grouping dan rendering pesan berada di `notification_formatting.py` pada direktori yang sama. Engine mempertahankan orchestration database dan transport. Pengujian kebijakan dapat memasukkan `policy` dan `current_time` secara eksplisit agar batas waktu dapat diuji tanpa mengubah konfigurasi global.

`evaluate_alerts(..., notification_writer=...)` menyediakan jalur enqueue transaksional untuk integrasi outbox. Writer harus memakai session yang diberikan tanpa commit atau network I/O. Dengan `commit=True`, engine commit setelah enqueue sukses; dengan `commit=False`, transaksi pemanggil menentukan commit/rollback. Writer produksi belum terpasang: routing, idempotency, grouping, dan serialisasi producer harus dituntaskan sebelum aktivasi. Tanpa writer, perilaku pengiriman lama tetap berlaku.

Adapter `TelegramOutboxWriter("<numeric-chat-id>")` memerlukan migration `0029`, menyimpan tujuan dan message, dan mengunci stream sampai transaksi selesai. Job dengan destination harus dikirim melalui `routed_sender(destination, message)`; tidak ada fallback diam-diam ke chat konfigurasi terbaru. Adapter masih opt-in. Grup besar dipecah menjadi job dengan batas 4096 unit UTF-16 dan 250 referensi; satu event yang sendirian terlalu besar serta konflik routing pending masih ditolak. Setiap potongan mempunyai acknowledgement sendiri. Migration `0029` belum diterapkan ke database Compose lokal pada tahap implementasi ini.

Pada jalur outbox, evaluator/writer dan acknowledgement memakai urutan lock alert sebelum job. Validasi lease dilakukan setelah lock diperoleh. Reminder membawa asumsi generasi delivery dari selection; adapter melewatinya jika timestamp delivery berubah, sehingga cooldown dapat dihitung ulang pada evaluasi berikutnya.
