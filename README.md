# Network Monitoring

Project monitoring internal untuk:
- target internet
- Mikrotik
- server
- device penting
- alert dan incident dasar
- dashboard internal

## Stack
- FastAPI
- MySQL
- SQLAlchemy
- APScheduler
- Streamlit
- psutil
- ping3
- librouteros

## Struktur Utama
- `backend/app/main.py`: boot FastAPI API-only, init DB bootstrap
- `backend/app/scheduler/worker.py`: proses scheduler terpisah untuk monitoring jobs
- `backend/app/monitors/*`: internet, device, server, Mikrotik checks
- `backend/app/alerting/*`: evaluasi alert, notifier, incident lifecycle
- `backend/app/api/routes/*`: endpoint dashboard, devices, metrics, alerts, incidents, system
- `dashboard/*`: Streamlit UI
- `scripts/bootstrap_demo.py`: seed device + jalankan satu monitoring cycle
- `scripts/run_monitor_cycle.py`: trigger satu monitoring cycle manual
- `scripts/test_snmp.py`: test SNMP v2c ke printer dari host lokal

## Persiapan

1. Buat dan aktifkan virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate
```

2. Install dependency development

```bash
python -m pip install -r requirements.txt
```

Untuk install yang lebih lean per service:

```bash
python -m pip install -r requirements/backend.txt
python -m pip install -r requirements/dashboard.txt
```

3. Siapkan environment file

```bash
copy .env.example .env
```

Untuk printer SNMP, isi `PRINTER_SNMP_COMMUNITIES` dengan JSON map IP ke community, misalnya:

```bash
PRINTER_SNMP_COMMUNITIES={"192.168.88.38":"community-printer-1","192.168.88.145":"community-printer-2"}
```

4. Jalankan MySQL

```bash
docker compose up -d mysql
```

5. Jalankan migration database untuk setup lokal tanpa Docker Compose

```bash
alembic upgrade head
```

## Bootstrap Awal

Inisialisasi tabel, seed device awal, lalu jalankan satu siklus monitoring:

```bash
python scripts/bootstrap_demo.py
```

Kalau ingin seed threshold saja:

```bash
python scripts/seed_thresholds.py
```

Kalau hanya ingin menjalankan satu siklus monitoring manual:

```bash
python scripts/run_monitor_cycle.py
```

Kalau ingin benchmark endpoint backend lokal:

```bash
python scripts/benchmark_endpoints.py --base-url http://localhost:8000 --runs 5
```

## Menjalankan Backend API

```bash
uvicorn backend.app.main:app --reload
```

## Menjalankan Scheduler Worker

```bash
python -m backend.app.scheduler.worker
```

Semua endpoint API operasional selain `GET /health` sekarang membutuhkan salah satu:
- header `Authorization: Bearer <token>` dari login user backend
- atau header `x-api-key` untuk automation/internal integration

API key internal sekarang mendukung scope terpisah:
- `read` untuk endpoint baca
- `write` untuk mutasi inventory/threshold
- `ops` untuk aksi operasional seperti `POST /system/run-cycle`

Format `INTERNAL_API_KEYS`:

```bash
reader:reader-secret:read
writer:writer-secret:read,write
operator:ops-secret:read,ops
```

Endpoint mutasi seperti `POST /devices`, `PUT /devices/{id}`, `PUT /thresholds/{key}`, dan
`POST /system/run-cycle` membutuhkan user role `admin` bila memakai bearer token. Bila memakai API key,
scope yang dibutuhkan sekarang eksplisit (`write` atau `ops`), bukan full admin generik.

API utama:
- `GET /dashboard/summary`
- `GET /dashboard/overview-panels`
- `GET /dashboard/problem-devices`
- `GET /devices`
- `GET /devices/paged`
- `POST /devices`
- `PUT /devices/{device_id}`
- `GET /metrics/history`
- `GET /metrics/history/paged`
- `GET /alerts/active`
- `GET /incidents`
- `GET /thresholds`
- `GET /observability/summary`
- `GET /observability/metrics`
- `GET /auth/admin/users`
- `POST /auth/admin/users`
- `PUT /auth/admin/users/{user_id}`
- `POST /auth/admin/users/{user_id}/reset-password`
- `GET /auth/admin/audit-logs`
- `POST /auth/change-password`
- `PUT /thresholds/{key}`
- `POST /system/run-cycle`

## Menjalankan Dashboard

```bash
streamlit run dashboard/Overview.py
```

Dashboard sekarang login ke backend memakai akun user monitoring.
Admin awal bisa dibootstrap lewat environment:
- `BOOTSTRAP_ADMIN_USERNAME`
- `BOOTSTRAP_ADMIN_FULL_NAME`
- `BOOTSTRAP_ADMIN_PASSWORD`
- `AUTH_JWT_SECRET` untuk secret signing JWT yang dedicated

Setelah backend hidup, login dashboard menggunakan akun tersebut.

## Menjalankan Dengan Docker Compose

Jalankan migration sebagai release/init step dulu:

```bash
docker compose run --rm migrate
```

Build dan jalankan seluruh stack:

```bash
docker compose up --build
```

Service default:
- MySQL di `localhost:3306`
- FastAPI backend API-only di `http://localhost:8000`
- scheduler worker terpisah di service `scheduler`
- migration dijalankan explicit lewat service one-shot `migrate`
- Streamlit dashboard di `http://localhost:8501`

Catatan auth dashboard:
- `DASHBOARD_API_URL` boleh tetap mengarah ke host internal container seperti `http://backend:8000`.
- Untuk login dashboard berbasis browser cookie, set `DASHBOARD_PUBLIC_API_URL` ke URL backend yang bisa diakses browser user, default Docker Compose sekarang `http://localhost:8000`.

Container backend dan scheduler sekarang tidak menjalankan migration otomatis saat startup.
Migration dipindahkan ke explicit release/init step lewat `docker compose run --rm migrate`.
Compose juga memakai healthcheck: backend menunggu MySQL sehat, dashboard menunggu backend sehat,
dan `/health` akan mengembalikan HTTP 503 kalau database belum siap.
Di `APP_ENV=production`, backend tidak menjalankan `create_all()` saat startup; schema database
dikelola lewat Alembic migration.

Dashboard utama sekarang bisa:
- melihat summary status internet, server, Mikrotik, dan alert aktif
- trigger manual monitoring cycle
- melihat daftar device dengan filter server-side dan pagination
- melihat alert aktif
- melihat incident aktif/resolved
- melihat histori metric dengan filter waktu dan chart untuk metric numerik
- melihat dan mengubah threshold alert

## Security

- Jangan pakai password database default di production. `.env` lokal sudah memakai kredensial random yang digenerate untuk mesin ini.
- Set `APP_ENV=production`, isi `BOOTSTRAP_ADMIN_PASSWORD`, dan gunakan password admin yang kuat.
- Isi `AUTH_JWT_SECRET` dengan secret acak yang panjang agar signing JWT tidak bergantung pada fallback internal.
- `INTERNAL_API_KEY` tetap didukung untuk script/internal integration, tapi dashboard normal sekarang memakai login user + bearer token.
- Untuk deployment baru, lebih baik pakai `INTERNAL_API_KEYS` dengan scope spesifik daripada satu `INTERNAL_API_KEY` global.
- Password user disimpan sebagai hash PBKDF2, access token memakai JWT HS256, session di database menyimpan `jti` untuk revocation, dan endpoint write memerlukan role `admin`.
- Password policy sekarang enforce minimum length (`AUTH_PASSWORD_MIN_LENGTH`) plus uppercase, lowercase, digit, dan simbol.
- Login sekarang memakai rate limit berbasis database per kombinasi username dan client IP untuk menahan brute-force dasar di deployment multi-instance.
- Jika backend berada di balik reverse proxy, isi `TRUSTED_PROXY_IPS` agar `X-Forwarded-For` hanya dipercaya dari proxy yang memang kamu kontrol.
- Production sekarang fail-fast saat boot jika security default masih longgar, termasuk `AUTH_COOKIE_SECURE=false`, `ALLOW_INSECURE_NO_AUTH=true`, `INTERNAL_API_KEY` kosong, `TRUSTED_HOSTS` masih localhost-only, atau `CORS_ORIGINS` non-HTTPS untuk origin non-local.
- Cleanup scheduler juga merapikan `auth_sessions` kadaluarsa/revoked dan riwayat `auth_login_attempts` lama agar tabel auth tidak tumbuh tanpa batas.
- Backend juga menyediakan inventory session aktif lewat `GET /auth/sessions` dan revoke semua session lain lewat `POST /auth/logout-all` untuk kebutuhan operasional/account recovery.
- Touch `last_seen_at` session sekarang ditahan per interval (`AUTH_SESSION_TOUCH_INTERVAL_SECONDS`) agar request API yang sering tidak memicu write database di setiap hit.
- Session bootstrap admin dijalankan saat startup jika `BOOTSTRAP_ADMIN_PASSWORD` disediakan dan username tersebut belum ada.
- Admin sekarang punya audit trail terstruktur di `admin_audit_logs` untuk mutasi penting seperti create/update device, update threshold, run-cycle manual, create/update user, reset password, dan revoke session massal.
- Backend membatasi `Host` header, menambahkan security headers dasar, dan mematikan `/docs`, `/redoc`, `/openapi.json` di production.
- Docker Compose default sekarang publish MySQL, backend, dan dashboard ke `127.0.0.1` saja agar tidak terbuka ke LAN secara tidak sengaja.
- `.env` masuk `.gitignore`; simpan secret production di secret manager atau environment deployment.
- Overlap guard monitoring sekarang pakai named database lock (`MONITORING_LOCK_NAME`) di MySQL, jadi aman lintas process/container untuk scheduler worker dan manual run-cycle.

## Testing

```bash
python -m pytest
```

Lint baseline:

```bash
ruff check backend dashboard scripts tests
```

## Benchmark

Script benchmark sederhana tersedia untuk mengukur latency endpoint yang sering dipakai dashboard:

```bash
python scripts/benchmark_endpoints.py --base-url http://localhost:8000 --runs 10
```

Opsional:
- `--path /dashboard/summary`
- `--path /devices/paged?limit=100&offset=0`
- `--path /metrics/history/paged?limit=100&offset=0`
- `--api-key your-internal-key`
- `--max-p95-ms 1500`
- `--max-max-ms 2500`

Smoke concurrency sederhana:

```bash
python scripts/concurrency_smoke.py --base-url http://localhost:8000 --path /health/live --requests 20 --concurrency 5 --max-p95-ms 1000
```

## CI

Repository sekarang punya GitHub Actions pipeline di `.github/workflows/ci.yml` untuk:
- lint baseline dengan Ruff
- unit/API test dengan pytest
- migration smoke test ke MySQL
- benchmark regression gate dan concurrency smoke test
- build image backend dan dashboard
- dependency security audit dengan `pip-audit`

## Migration

Generate migration baru setelah schema berubah:

```bash
alembic revision --autogenerate -m "describe change"
```

Apply migration terbaru:

```bash
alembic upgrade head
```

Untuk Docker Compose production-like, jalankan:

```bash
docker compose run --rm migrate
```

## Catatan Implementasi
- Scheduler tidak lagi ikut hidup di proses API; jalankan worker terpisah atau service `scheduler`
- Monitor internet/device memakai `ping3`
- Monitor printer sekarang memakai kombinasi ping + SNMP v2c untuk uptime, status printer, error state, paper status, counter halaman, dan ink level jika printer mengeksposnya
- Monitor server memakai `psutil` untuk CPU, memory, disk, dan boot time
- Monitor Mikrotik mencoba akses RouterOS API jika kredensial di `.env` tersedia
- Alert aktif akan menghasilkan incident aktif per device
- Threshold alert disimpan di database dan otomatis dibuat saat belum ada
- Endpoint mutasi seperti `POST /devices`, `PUT /devices/{device_id}`, `PUT /thresholds/{key}`, dan `POST /system/run-cycle` memakai header `x-api-key`
- Endpoint `GET /health` dan `GET /observability/summary` bisa dipakai untuk readiness check dan ringkasan operasional
- Overview dashboard sekarang tidak lagi bergantung ke satu endpoint besar; panel agregat, daftar problem devices, dan history/snapshot dipecah supaya auto-refresh lebih ringan saat data tumbuh.
- Connection pool database sekarang bisa dituning lewat `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS`, dan `DB_POOL_RECYCLE_SECONDS`.
- Retention raw metrics sekarang tidak hanya delete: data yang melewati cutoff juga diarsipkan ke `metric_cold_archives` sebagai agregat cold-storage per device/hari/metric/status sebelum raw rows dipruning.
- Concurrency runner monitor sekarang dibatasi lewat `MONITOR_TASK_CONCURRENCY_LIMIT` supaya inventory besar tidak memicu `asyncio.gather` tak terbatas di satu tick scheduler.
- Health endpoint sekarang dipisah jadi `/health/live`, `/health/ready`, dan `/health/dependencies`, sementara `/health` tetap jadi ringkasan cepat.
- Logging backend sekarang siap ingestion dengan JSON structured logging, `X-Request-ID`, slow request logging, dan correlation field lintas HTTP/scheduler.
- Observability backend sekarang punya metrics scrape endpoint Prometheus-style di `/observability/metrics` dan status job scheduler disimpan di DB untuk deteksi stale/failure lintas process.

## Checklist Arsitektur
- Backend API, DB session, dan HTTP outbound utama sudah async-friendly.
- Library blocking seperti `ping3`, `psutil`, dan `librouteros` diisolasi lewat `asyncio.to_thread`.
- Monitoring cycle berjalan paralel dengan session terpisah per runner, lalu persist dan evaluasi alert di fase akhir.
- Scheduler worker dan manual run-cycle sudah punya distributed guard berbasis DB lock supaya tidak overlap lintas replica/container.
- Endpoint list besar yang dipakai dashboard sudah punya versi paged untuk menjaga performa saat data tumbuh.
- Retention rollup sudah diproses secara streaming agar tidak memuat semua raw metric lama ke memory sekaligus.
- Dashboard Streamlit tetap model sinkron, jadi optimasi difokuskan ke query server-side, pagination, dan pengurangan kerja dataframe di client.

## Posisi Streamlit

Dashboard Streamlit di project ini diposisikan sebagai frontend internal ops, bukan public web app multi-user skala besar.

Masih cocok untuk:
- dashboard internal tim kecil
- troubleshooting harian
- auto-refresh ringan dengan pagination server-side

Mulai tidak ideal jika:
- banyak user aktif bersamaan
- kebutuhan UX makin kompleks dan stateful
- perlu kontrol frontend yang lebih presisi untuk auth, navigation, dan real-time updates

Kalau kebutuhan sudah ke arah itu, jalur upgrade yang lebih aman biasanya memindahkan UI ke frontend web dedicated, sementara FastAPI tetap jadi API/backend observability.
