# Network Monitoring

Network Monitoring adalah aplikasi monitoring internal untuk memantau koneksi internet, Mikrotik, server, printer, dan device penting di jaringan kantor. Project ini memisahkan backend API, scheduler worker, database, dan dashboard agar proses monitoring tidak bergantung pada proses web API.

Project ini cocok untuk:
- monitoring internal tim IT/ops
- inventory device sederhana
- pengecekan ping, DNS, HTTP, public IP, SNMP printer, resource server, dan RouterOS Mikrotik
- alert dan incident dasar
- dashboard operasional berbasis Streamlit

## Ringkasan Stack

- Python 3.12
- FastAPI untuk backend API
- Streamlit untuk dashboard internal
- MySQL 8.4 untuk database utama
- SQLAlchemy async + Alembic untuk persistence dan migration
- APScheduler untuk worker monitoring periodik
- `ping3`, `httpx`, `psutil`, `librouteros`, dan `pysnmp` untuk collector
- Ruff, pytest, mypy/pyright, pip-audit, Bandit, Semgrep, Gitleaks, dan GitHub Actions untuk quality gate

## Arsitektur Singkat

```mermaid
flowchart LR
    Browser["Browser user"] --> Dashboard["Streamlit dashboard"]
    Dashboard --> API["FastAPI backend"]
    API --> DB["MySQL"]
    Scheduler["Scheduler worker"] --> DB
    Scheduler --> Collectors["Monitoring collectors"]
    Collectors --> Internet["Internet targets"]
    Collectors --> Devices["Network devices"]
    Collectors --> Printer["Printer SNMP"]
    Collectors --> Server["Local server metrics"]
    Collectors --> Mikrotik["Mikrotik RouterOS API"]
    Scheduler --> Alerts["Alert engine"]
    Alerts --> DB
    Alerts --> Telegram["Telegram notifier optional"]
```

Runtime utama:
- `backend/app/main.py`: FastAPI API-only process.
- `backend/app/scheduler/worker.py`: worker APScheduler terpisah.
- `dashboard/Overview.py`: entry point Streamlit dashboard.
- `alembic/versions/*`: migration database.
- `scripts/*`: bootstrap, maintenance, benchmark, smoke test, dan utilitas ops.

## Struktur Project

```text
backend/
  app/
    api/             FastAPI dependencies, schemas, routes
    alerting/        rule alert, evaluasi alert, Telegram notifier
    core/            config, security, constants, time helper
    db/              engine, session, init DB
    models/          SQLAlchemy ORM models
    monitors/        internet, device, printer SNMP, server, Mikrotik collectors
    repositories/    query dan persistence per domain
    scheduler/       APScheduler job registration dan worker
    services/        business workflow, auth, retention, observability
dashboard/
  Overview.py        halaman utama Streamlit
  pages/             Devices, Alerts, History, Incidents, Thresholds
  components/        auth, API client, UI, refresh, time utility
alembic/             migration environment dan revision files
scripts/             bootstrap, seed, backfill, benchmark, smoke, SNMP test
tests/               API, service, dashboard component, monitor tests
requirements/        dependency per service dan dev tooling
```

Semua module, class, function, helper function, dan method Python sudah diberi docstring agar orang baru lebih gampang membaca kode.

## Quick Start Dengan Docker Compose

Cara ini paling dekat dengan runtime production-like lokal.

1. Copy environment file.

```bash
copy .env.example .env
```

2. Edit `.env`, minimal isi nilai berikut dengan secret kuat.

```env
APP_ENV=production
MYSQL_PASSWORD=replace-with-a-strong-password
MYSQL_ROOT_PASSWORD=replace-with-a-separate-strong-root-password
AUTH_PASSWORD_SECRET=replace-with-a-long-random-password-secret
AUTH_JWT_SECRET=replace-with-a-long-random-jwt-secret
BOOTSTRAP_ADMIN_USERNAME=admin
BOOTSTRAP_ADMIN_FULL_NAME=Monitoring Admin
BOOTSTRAP_ADMIN_PASSWORD=replace-with-a-strong-admin-password
INTERNAL_API_KEYS=operator:replace-with-ops-key:read,write,ops
CORS_ORIGINS=http://localhost:8501,http://127.0.0.1:8501
TRUSTED_HOSTS=localhost,127.0.0.1,backend
DASHBOARD_PUBLIC_API_URL=http://localhost:8000
AUTH_COOKIE_SECURE=false
```

Untuk deployment HTTPS sungguhan, `AUTH_COOKIE_SECURE` harus `true`, `CORS_ORIGINS` sebaiknya HTTPS, dan `TRUSTED_HOSTS` harus berisi hostname asli.

3. Jalankan MySQL.

```bash
docker compose up -d mysql
```

4. Jalankan migration.

```bash
docker compose --profile ops run --rm migrate
```

5. Build dan jalankan backend, scheduler, dan dashboard.

```bash
docker compose up --build
```

Service default:
- MySQL: `127.0.0.1:3306`
- Backend API: `http://localhost:8000`
- Dashboard: `http://localhost:8501`
- Scheduler: service `scheduler`, tidak expose port

Login dashboard memakai akun bootstrap admin dari `BOOTSTRAP_ADMIN_USERNAME` dan `BOOTSTRAP_ADMIN_PASSWORD`.

## Quick Start Lokal Tanpa Compose Full Stack

Gunakan ini kalau mau development langsung dari host.

1. Buat virtual environment.

```bash
python -m venv venv
venv\Scripts\activate
```

2. Install dependency.

```bash
python -m pip install -r requirements/dev.txt
```

Untuk install lebih ringan:

```bash
python -m pip install -r requirements/backend.txt
python -m pip install -r requirements/dashboard.txt
```

3. Siapkan `.env`.

```bash
copy .env.example .env
```

Untuk development lokal, set minimal:

```env
APP_ENV=development
DATABASE_URL=mysql+pymysql://network_monitoring:your-password@localhost:3306/network_monitoring
AUTH_PASSWORD_SECRET=dev-password-secret-change-me
AUTH_JWT_SECRET=dev-jwt-secret-change-me
BOOTSTRAP_ADMIN_USERNAME=admin
BOOTSTRAP_ADMIN_FULL_NAME=Monitoring Admin
BOOTSTRAP_ADMIN_PASSWORD=AdminPassword123!
INTERNAL_API_KEY=dev-internal-key
CORS_ORIGINS=http://localhost:8501,http://127.0.0.1:8501
TRUSTED_HOSTS=localhost,127.0.0.1
AUTH_COOKIE_SECURE=false
DASHBOARD_API_URL=http://localhost:8000
DASHBOARD_PUBLIC_API_URL=http://localhost:8000
```

4. Jalankan MySQL.

```bash
docker compose up -d mysql
```

5. Apply migration.

```bash
alembic upgrade head
```

6. Jalankan backend API.

```bash
uvicorn backend.app.main:app --reload
```

7. Jalankan scheduler worker di terminal lain.

```bash
python -m backend.app.scheduler.worker
```

8. Jalankan dashboard di terminal lain.

```bash
streamlit run dashboard/Overview.py
```

Catatan: di `APP_ENV=development`, backend juga memanggil `create_all()` saat startup untuk memudahkan lokal, tapi tetap disarankan memakai Alembic agar schema konsisten.

## Alur Data Monitoring

1. Scheduler menjalankan job periodik untuk internet, device, server, Mikrotik, alert evaluation, dan cleanup.
2. Collector menghasilkan payload metric dengan `device_id`, `metric_name`, `metric_value`, `metric_value_numeric`, `status`, `unit`, dan `checked_at`.
3. `MetricRepository.create_metrics()` menyimpan metric raw dan meng-update tabel `latest_metrics` sebagai snapshot terbaru per device/metric.
4. Alert engine membaca latest metric, threshold, active alert, dan active incident.
5. Alert baru dibuat kalau kondisi masih buruk; alert diselesaikan kalau kondisi membaik.
6. Incident aktif dibuat per device saat alert pertama muncul, lalu resolved saat alert untuk device tersebut sudah clear.
7. Dashboard membaca summary, overview panels, problem devices, latest snapshot, history, alerts, incidents, thresholds, dan auth/admin data dari API.

Monitoring pipeline dilindungi `MONITORING_LOCK_NAME` memakai MySQL named lock, sehingga scheduler dan manual `run-cycle` tidak saling overlap lintas process/container.

## Collector Yang Tersedia

### Internet Target

Device type: `internet_target`

Metric:
- `ping`
- `packet_loss`
- `jitter`
- `dns_resolution_time`
- `http_response_time`
- `public_ip`

DNS, HTTP, dan public IP memakai satu anchor internet target. Pemilihan anchor memprioritaskan nama yang mengandung `myrepublic`, lalu `isp`, lalu device lain, lalu `mikrotik`.

### Device Umum

Device type:
- `nvr`
- `switch`
- `access_point`
- `voip`
- `printer`

Metric:
- `ping`
- `packet_loss` dan `jitter` untuk `access_point`, `voip`, dan `printer`
- ping sederhana untuk `nvr` dan `switch`

### Printer SNMP

Device type: `printer`

Selain ping quality, printer dapat mengumpulkan SNMP v2c jika `PRINTER_SNMP_COMMUNITIES` diisi.

Metric:
- `printer_uptime_seconds`
- `printer_status`
- `printer_error_state`
- `printer_ink_status`
- `printer_paper_status`
- `printer_total_pages`

Format `PRINTER_SNMP_COMMUNITIES` bisa JSON map:

```env
PRINTER_SNMP_COMMUNITIES={"192.168.88.38":"community-printer-1","192.168.88.145":"community-printer-2"}
```

Atau format baris `ip=community` yang dipisah newline/koma.

### Server

Device type: `server`

Metric:
- `ping`
- `cpu_percent`
- `memory_percent`
- `disk_percent`
- `boot_time_epoch`

Resource server memakai `psutil` dari host/container tempat scheduler berjalan. Jika scheduler berjalan di container, resource yang terbaca adalah environment container/host sesuai akses container.

Catatan multi-server:
- Jika hanya ada satu device `server` aktif, metrik resource langsung dipetakan ke device tersebut.
- Jika ada lebih dari satu device `server`, set `SERVER_RESOURCE_DEVICE_IP` supaya atribusi metrik resource tidak salah device.
- Tanpa `SERVER_RESOURCE_DEVICE_IP`, metrik `cpu_percent`, `memory_percent`, `disk_percent`, `boot_time_epoch` akan di-skip untuk mencegah data salah label.

### Mikrotik

Device type: `mikrotik`, atau nama device mengandung `mikrotik`.

Metric dasar:
- `ping`
- `packet_loss`
- `jitter`
- `mikrotik_api`
- `cpu_percent`
- `memory_percent`
- `memory_used_bytes`
- `memory_free_bytes`
- `disk_percent`
- `disk_used_bytes`
- `disk_free_bytes`
- `interfaces_running`
- `dhcp_active_leases`
- `connected_clients`

Metric dinamis RouterOS:
- `interface:<name>:rx_mbps`
- `interface:<name>:tx_mbps`
- `interface:<name>:rx_pps`
- `interface:<name>:tx_pps`
- `firewall:<section>:<rule>:pps`
- `firewall:<section>:<rule>:mbps`
- `queue:<name>:download_mbps`
- `queue:<name>:upload_mbps`

Konfigurasi Mikrotik utama:
- `MIKROTIK_HOST`
- `MIKROTIK_PORT`
- `MIKROTIK_USERNAME`
- `MIKROTIK_PASSWORD`
- `MIKROTIK_DYNAMIC_SECTIONS`
- `MIKROTIK_DYNAMIC_FIREWALL_SECTION_ALLOWLIST`
- `MIKROTIK_DYNAMIC_INTERFACE_ALLOWLIST`
- `MIKROTIK_DYNAMIC_QUEUE_ALLOWLIST`
- `MIKROTIK_DYNAMIC_MAX_INTERFACES`
- `MIKROTIK_DYNAMIC_MAX_FIREWALL_RULES`
- `MIKROTIK_DYNAMIC_MAX_QUEUES`

## Device Type

Device type yang valid:
- `internet_target`
- `mikrotik`
- `server`
- `nvr`
- `switch`
- `access_point`
- `voip`
- `printer`

Device memiliki field utama:
- `name`
- `ip_address`
- `device_type`
- `site`
- `description`
- `is_active`

Device inactive tetap ada di inventory, tapi tidak ikut collector bila query memakai `active_only=True`.

## Alert, Incident, Dan Threshold

Threshold default otomatis dibuat ketika threshold dibaca pertama kali.

Threshold yang tersedia:
- `ping_latency_warning`
- `ping_latency_critical`
- `cpu_warning`
- `ram_warning`
- `disk_warning`
- `packet_loss_warning`
- `packet_loss_critical`
- `jitter_warning`
- `jitter_critical`
- `dns_resolution_warning`
- `http_response_warning`
- `mikrotik_connected_clients_warning`
- `mikrotik_interface_mbps_warning`
- `mikrotik_firewall_spike_pps_warning`
- `mikrotik_firewall_spike_mbps_warning`
- `printer_ink_warning`
- `printer_ink_critical`

Alert rule utama:
- device down atau internet loss
- high ping latency
- high packet loss
- high jitter
- DNS failed atau slow DNS
- HTTP failed atau slow HTTP
- public IP changed
- high CPU/RAM/disk
- Mikrotik API failed
- connected clients tinggi
- interface traffic tinggi
- firewall spike
- printer reboot/status/error/paper/ink issue

Alert aktif dikaitkan ke incident aktif per device. Incident resolved otomatis setelah semua alert aktif untuk device tersebut clear.

Telegram notification optional memakai:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Auth Dan Security

Backend menjalankan `validate_auth_configuration()` saat startup. `AUTH_PASSWORD_SECRET` dan `AUTH_JWT_SECRET` wajib ada.

Auth user:
- password disimpan dengan PBKDF2 SHA-256
- access token memakai JWT HS256
- refresh/session state disimpan di tabel `auth_sessions`
- session punya `jti` untuk revocation
- login attempt dicatat di `auth_login_attempts`
- password policy mewajibkan minimum length, uppercase, lowercase, digit, dan symbol

Role user:
- `admin`: bisa read, write, ops, admin endpoints
- `viewer`: read-only dashboard/API

API key internal:
- legacy `INTERNAL_API_KEY` tetap didukung dan mendapat scope `read`, `write`, `ops`
- rekomendasi baru adalah `INTERNAL_API_KEYS` dengan scope eksplisit

Format `INTERNAL_API_KEYS`:

```env
reader:reader-secret:read
writer:writer-secret:read,write
operator:ops-secret:read,ops
```

Atau JSON:

```json
{
  "operator": {
    "key": "ops-secret",
    "scopes": ["read", "write", "ops"]
  }
}
```

Permission endpoint:
- endpoint read membutuhkan bearer token valid atau API key scope `read`
- endpoint write seperti device/threshold mutation membutuhkan user `admin` atau API key scope `write`
- endpoint ops seperti `POST /system/run-cycle` membutuhkan user `admin` atau API key scope `ops`
- endpoint admin auth management membutuhkan user `admin`

Production fail-fast jika:
- `ALLOW_INSECURE_NO_AUTH=true`
- `AUTH_COOKIE_SECURE=false`
- tidak ada `INTERNAL_API_KEY` atau `INTERNAL_API_KEYS`
- `TRUSTED_HOSTS` hanya localhost
- `CORS_ORIGINS` kosong atau non-HTTPS untuk origin non-local

Security header yang dipasang:
- `X-Content-Type-Options`
- `X-Frame-Options`
- `Referrer-Policy`
- `Permissions-Policy`
- `Content-Security-Policy`
- `Strict-Transport-Security` saat request HTTPS

Docs API (`/docs`, `/redoc`, `/openapi.json`) mati otomatis di production.

## Environment Variables Penting

### App Dan Database

| Variable | Fungsi |
| --- | --- |
| `APP_NAME` | Nama aplikasi |
| `APP_ENV` | `development` atau `production` |
| `DATABASE_URL` | URL database SQLAlchemy, contoh MySQL `mysql+pymysql://...` |
| `MYSQL_DATABASE` | Nama database untuk Compose |
| `MYSQL_USER` | User MySQL untuk Compose |
| `MYSQL_PASSWORD` | Password MySQL untuk Compose |
| `MYSQL_ROOT_PASSWORD` | Root password MySQL untuk Compose |
| `DB_POOL_SIZE` | Pool size SQLAlchemy untuk non-SQLite |
| `DB_MAX_OVERFLOW` | Max overflow connection |
| `DB_POOL_TIMEOUT_SECONDS` | Timeout menunggu connection |
| `DB_POOL_RECYCLE_SECONDS` | Recycle connection pool |

### Auth

| Variable | Fungsi |
| --- | --- |
| `AUTH_PASSWORD_SECRET` | Pepper/secret untuk password hash |
| `AUTH_JWT_SECRET` | Secret signing JWT |
| `AUTH_TOKEN_TTL_MINUTES` | TTL access token |
| `AUTH_REMEMBER_TTL_MINUTES` | TTL refresh/session saat remember login |
| `AUTH_COOKIE_SECURE` | Cookie secure flag, wajib true di production HTTPS |
| `AUTH_COOKIE_SAMESITE` | SameSite cookie |
| `AUTH_LOGIN_RATE_LIMIT_MAX_ATTEMPTS` | Maksimal gagal login per window |
| `AUTH_LOGIN_RATE_LIMIT_WINDOW_MINUTES` | Window rate limit login |
| `AUTH_SESSION_TOUCH_INTERVAL_SECONDS` | Interval update `last_seen_at` |
| `AUTH_SESSION_RETENTION_DAYS` | Retention session lama |
| `AUTH_LOGIN_ATTEMPT_RETENTION_DAYS` | Retention login attempt lama |
| `AUTH_PASSWORD_MIN_LENGTH` | Minimum panjang password |
| `BOOTSTRAP_ADMIN_USERNAME` | Username admin pertama |
| `BOOTSTRAP_ADMIN_FULL_NAME` | Nama admin pertama |
| `BOOTSTRAP_ADMIN_PASSWORD` | Password admin pertama |

### API Access Dan Browser

| Variable | Fungsi |
| --- | --- |
| `INTERNAL_API_KEY` | API key legacy |
| `INTERNAL_API_KEYS` | API keys dengan scope |
| `ALLOW_INSECURE_NO_AUTH` | Fallback tanpa auth, jangan pakai production |
| `CORS_ORIGINS` | Origin dashboard/browser yang boleh akses backend |
| `TRUSTED_HOSTS` | Host header yang diterima FastAPI |
| `TRUSTED_PROXY_IPS` | Proxy yang dipercaya untuk `X-Forwarded-For` |
| `DASHBOARD_API_URL` | URL backend dari sisi server Streamlit |
| `DASHBOARD_PUBLIC_API_URL` | URL backend dari browser user untuk auth bridge |

### Monitoring

| Variable | Fungsi |
| --- | --- |
| `PING_TIMEOUT_SECONDS` | Timeout ping |
| `PING_SAMPLE_COUNT` | Jumlah sample ping untuk quality metric |
| `PING_CONCURRENCY_LIMIT` | Limit concurrent ping |
| `MONITOR_TASK_CONCURRENCY_LIMIT` | Limit concurrent task collector |
| `DNS_CHECK_HOST` | Host DNS check |
| `HTTP_CHECK_URL` | URL HTTP check |
| `PUBLIC_IP_CHECK_URL` | URL public IP check |
| `CPU_WARNING_THRESHOLD` | Default threshold CPU |
| `RAM_WARNING_THRESHOLD` | Default threshold RAM |
| `DISK_WARNING_THRESHOLD` | Default threshold disk |
| `SERVER_RESOURCE_DEVICE_IP` | IP device `server` yang menerima metrik resource lokal |
| `PRINTER_SNMP_COMMUNITIES` | Map IP printer ke SNMP community |

### Scheduler Dan Retention

| Variable | Fungsi |
| --- | --- |
| `SCHEDULER_ENABLED` | Enable scheduler worker |
| `SCHEDULER_INTERVAL_INTERNET_SECONDS` | Interval internet checks |
| `SCHEDULER_INTERVAL_DEVICE_SECONDS` | Interval device checks |
| `SCHEDULER_INTERVAL_SERVER_SECONDS` | Interval server checks |
| `SCHEDULER_INTERVAL_MIKROTIK_SECONDS` | Interval Mikrotik checks |
| `SCHEDULER_INTERVAL_ALERT_SECONDS` | Interval alert evaluation |
| `SCHEDULER_CLEANUP_INTERVAL_HOURS` | Interval cleanup/retention |
| `SCHEDULER_JOB_STALE_FACTOR` | Faktor stale job untuk operational alert |
| `MONITORING_LOCK_NAME` | Nama MySQL lock monitoring pipeline |
| `MONITORING_LOCK_TIMEOUT_SECONDS` | Timeout lock monitoring |
| `RAW_METRIC_RETENTION_DAYS` | Retention raw metrics |
| `RETENTION_ROLLUP_BATCH_SIZE` | Batch rollup harian |
| `RETENTION_ARCHIVE_BATCH_SIZE` | Batch archive cold metrics |
| `ALERT_RETENTION_DAYS` | Retention alert resolved |
| `INCIDENT_RETENTION_DAYS` | Retention incident resolved |

### Logging Dan Observability

| Variable | Fungsi |
| --- | --- |
| `LOG_LEVEL` | Level log |
| `LOG_AS_JSON` | Output log structured JSON |
| `OBSERVABILITY_ENABLE_METRICS` | Enable metrics observability |
| `REQUEST_SLOW_LOG_THRESHOLD_MS` | Threshold slow request log |
| `PROMETHEUS_MULTIPROC_DIR` | Direktori shared metrics untuk mode multi-worker Prometheus |

### File-Backed Secret

Settings juga mendukung secret dari file:
- `TELEGRAM_BOT_TOKEN_FILE`
- `TELEGRAM_CHAT_ID_FILE`
- `MIKROTIK_PASSWORD_FILE`
- `INTERNAL_API_KEY_FILE`
- `AUTH_PASSWORD_SECRET_FILE`
- `PRINTER_SNMP_COMMUNITIES_FILE`
- `BOOTSTRAP_ADMIN_PASSWORD_FILE`
- `AUTH_JWT_SECRET_FILE`

Policy:
- `*_FILE` hanya boleh dipakai saat `APP_ENV=production`.
- Jika `*_FILE` dipakai di `development`/`test`, backend akan fail-fast saat load settings.
- Saat `*_FILE` aktif, nilai file akan override nilai env biasa (`AUTH_JWT_SECRET`, dll) untuk field yang sama.

Contoh konfigurasi production:

```env
APP_ENV=production
AUTH_JWT_SECRET_FILE=/run/secrets/auth_jwt_secret
AUTH_PASSWORD_SECRET_FILE=/run/secrets/auth_password_secret
BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/secrets/bootstrap_admin_password
INTERNAL_API_KEY_FILE=/run/secrets/internal_api_key
```

## API Utama

Semua endpoint operasional selain `/health/*` membutuhkan bearer token atau API key.

### Health

- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `GET /health/dependencies`

`/health/ready` hanya gagal jika database tidak siap. Scheduler degraded tetap dilaporkan di payload agar backend tidak dianggap down hanya karena job monitoring bermasalah.

### Auth

- `POST /auth/login`
- `POST /auth/restore`
- `GET /auth/me`
- `GET /auth/sessions`
- `POST /auth/logout-all`
- `POST /auth/change-password`
- `POST /auth/logout`
- `GET /auth/admin/sessions`
- `POST /auth/admin/users/{user_id}/logout-all`
- `GET /auth/admin/users`
- `POST /auth/admin/users`
- `PUT /auth/admin/users/{user_id}`
- `POST /auth/admin/users/{user_id}/reset-password`
- `GET /auth/admin/audit-logs`

### Dashboard

- `GET /dashboard/summary`
- `GET /dashboard/overview-panels`
- `GET /dashboard/problem-devices`
- `GET /dashboard/overview-data`

### Devices

- `GET /devices/meta/types`
- `GET /devices/status-summary`
- `GET /devices/options`
- `GET /devices`
- `GET /devices/paged`
- `GET /devices/{device_id}`
- `POST /devices`
- `PUT /devices/{device_id}`
- `DELETE /devices/{device_id}`

### Metrics

- `GET /metrics/names`
- `GET /metrics/history`
- `GET /metrics/history/paged`
- `GET /metrics/history/context`
- `GET /metrics/latest-snapshot/paged`
- `GET /metrics/latest-snapshot/status-summary`
- `GET /metrics/latest-snapshot/uptime-map`

### Alerts, Incidents, Thresholds, System

- `GET /alerts/active`
- `GET /alerts/active/paged`
- `GET /incidents`
- `GET /incidents/paged`
- `GET /thresholds`
- `PUT /thresholds/{key}`
- `POST /system/run-cycle`

Query filter paged yang umum dipakai dashboard:
- `/alerts/active/paged`: `severity`, `search`, `limit`, `offset`
- `/incidents/paged`: `status`, `search`, `limit`, `offset`

### API Lifecycle (Legacy Non-Paged Endpoint)

Untuk konsistensi kontrak API jangka panjang, endpoint list non-paged berikut masuk fase deprecasi:
- `/devices` -> migrasi ke `/devices/paged`
- `/alerts/active` -> migrasi ke `/alerts/active/paged`
- `/incidents` -> migrasi ke `/incidents/paged`
- `/metrics/history` -> migrasi ke `/metrics/history/paged`

Timeline Wave 6:
1. Announce date: `2026-04-24`
2. Warning window mulai: `2026-05-01`
3. Removal date target: `2026-10-31`

Selama warning window, response endpoint legacy akan menyertakan header:
- `Deprecation: true`
- `Sunset: Sat, 31 Oct 2026 00:00:00 GMT`
- `Warning: 299 ...`
- `X-API-Replacement-Endpoint`
- `X-API-Deprecation-Announced-On`
- `X-API-Deprecation-Warning-Window-Starts-On`
- `X-API-Deprecation-Removal-On`
- `X-API-Deprecation-Phase`

### Observability

- `GET /observability/summary`
- `GET /observability/metrics`

`/observability/metrics` menghasilkan format Prometheus text.

## Dashboard

Dashboard Streamlit ada di `dashboard/`.

Halaman:
- `Overview`: summary, KPI, problem devices, active alert, active incident, latest snapshot
- `Devices`: inventory device, filter, pagination, create/update/delete untuk admin
- `Alerts`: active alert
- `History`: metric history, latest snapshot, chart, dynamic Mikrotik/printer views
- `Incidents`: active/resolved incidents
- `Thresholds`: threshold alert dan update untuk admin

Auth dashboard:
- login memakai `/auth/login`
- session dipulihkan lewat `/auth/restore`
- browser cookie dikelola lewat auth bridge component
- request dashboard normal memakai bearer token session user
- API key tidak dipakai sebagai fallback user-facing dashboard

## Scheduler Jobs

Worker dijalankan dengan:

```bash
python -m backend.app.scheduler.worker
```

Job yang diregistrasi:
- `internet_checks`
- `device_checks`
- `server_checks`
- `mikrotik_checks`
- `alert_evaluation`
- `retention_cleanup`

Setiap job menyimpan status ke tabel `scheduler_job_statuses`, termasuk:
- running state
- consecutive failures
- last started/succeeded/failed
- last duration
- last error

Status ini dipakai health/observability untuk operational alert.

## Database Dan Migration

Migration memakai Alembic.

Apply migration:

```bash
alembic upgrade head
```

Generate migration baru:

```bash
alembic revision --autogenerate -m "describe change"
```

Docker Compose migration:

```bash
docker compose --profile ops run --rm migrate
```

Di production, backend tidak menjalankan `create_all()`. Schema harus dikelola lewat Alembic.

Model utama:
- `devices`
- `metrics`
- `latest_metrics`
- `metric_daily_rollups`
- `metric_cold_archives`
- `alerts`
- `incidents`
- `thresholds`
- `users`
- `auth_sessions`
- `auth_login_attempts`
- `admin_audit_logs`
- `scheduler_job_statuses`

## Retention Dan Data Lifecycle

Cleanup scheduler menjalankan:
- rollup raw metric lama ke `metric_daily_rollups`
- archive raw metric yang melewati cutoff ke `metric_cold_archives`
- delete raw metric yang melewati `RAW_METRIC_RETENTION_DAYS`
- delete alert resolved lama
- delete incident resolved lama
- cleanup auth session dan login attempt lama

Raw metric tetap dipakai untuk history detail jangka pendek. Rollup/archive dipakai agar data lama tetap punya ringkasan tanpa membesarkan tabel raw metrics terus-menerus.

## Scripts

### Bootstrap demo

Seed device contoh, seed threshold, lalu jalankan satu cycle monitoring.

```bash
python scripts/bootstrap_demo.py
```

### Seed devices

```bash
python scripts/seed_devices.py
```

Device contoh yang dibuat:
- Gateway Lokal
- Google DNS
- Cloudflare DNS
- Mikrotik Utama
- Server Monitoring
- NVR Kantor
- Switch Lantai 1
- AP Meeting Room
- Printer Finance

### Seed thresholds

```bash
python scripts/seed_thresholds.py
```

### Manual monitoring cycle

```bash
python scripts/run_monitor_cycle.py
```

Atau via API:

```bash
curl -X POST http://localhost:8000/system/run-cycle -H "x-api-key: dev-internal-key"
```

### SNMP printer test

```bash
python scripts/test_snmp.py --ip 192.168.88.38 --community public
```

### Backfill numeric metric

Dipakai setelah migration `metric_value_numeric` untuk mengisi numeric value dari metric lama.

```bash
python scripts/backfill_metric_numeric.py --batch-size 500
```

Dry run:

```bash
python scripts/backfill_metric_numeric.py --dry-run
```

### Benchmark endpoint

```bash
python scripts/benchmark_endpoints.py --base-url http://localhost:8000 --api-key dev-internal-key --profile ci --runs 10
```

Default benchmark path sudah fokus ke endpoint paged utama:
- `/devices/paged`
- `/alerts/active/paged`
- `/incidents/paged`
- `/metrics/history/paged`
- `/metrics/latest-snapshot/paged`
- `/metrics/daily-summary`

Opsional:

```bash
python scripts/benchmark_endpoints.py --base-url http://localhost:8000 --api-key dev-internal-key --profile custom --runs 10 --max-p95-ms 1500 --max-max-ms 2500
```

Simpan artifact JSON:

```bash
python scripts/benchmark_endpoints.py --base-url http://localhost:8000 --api-key dev-internal-key --profile ci --runs 10 --output-json .ci_artifacts/benchmark.json
```

### Concurrency smoke

```bash
python scripts/concurrency_smoke.py --base-url http://localhost:8000 --api-key dev-internal-key --profile ci --requests 10 --concurrency 5
```

Opsional path spesifik (bisa diulang):

```bash
python scripts/concurrency_smoke.py --base-url http://localhost:8000 --api-key dev-internal-key --profile custom --path /health/live --path /devices/paged?limit=50\&offset=0 --requests 20 --concurrency 5 --max-p95-ms 1500 --max-max-ms 2500
```

### Observability payload smoke

```bash
python scripts/observability_payload_smoke.py --base-url http://localhost:8000 --api-key dev-internal-key
```

Opsional endpoint ekspektasi custom (bisa diulang):

```bash
python scripts/observability_payload_smoke.py --base-url http://localhost:8000 --api-key dev-internal-key --expect-endpoint /devices/paged --expect-endpoint /metrics/history/paged
```

Simpan artifact JSON:

```bash
python scripts/observability_payload_smoke.py --base-url http://localhost:8000 --api-key dev-internal-key --output-json .ci_artifacts/observability_payload.json
```

## Testing, Lint, Dan Audit

Test:

```bash
python -m pytest
```

MySQL integration test (butuh DATABASE_URL mysql yang sudah dimigrasi):

```bash
python -m pytest tests/services/test_mysql_integration.py -q
```

Lint:

```bash
ruff check backend dashboard scripts tests
```

Lint staged quality-gate (Wave 3):

```bash
ruff check --select B,I,UP,SIM backend/app/services/auth backend/app/repositories/alert_repository.py backend/app/repositories/incident_repository.py
```

Type check staged quality-gate (Wave 3):

```bash
mypy --config-file mypy.ini
pyright
```

Dependency audit:

```bash
pip-audit -r requirements/backend.txt
pip-audit -r requirements/dashboard.txt
```

CI GitHub Actions menjalankan:
- Ruff lint
- Ruff staged rules (`B`, `I`, `UP`, `SIM`) untuk `backend/app/services/auth` dan repository yang sudah ditargetkan
- mypy staged type-check untuk `backend/app/services/auth` dan repository yang sudah ditargetkan
- pyright staged type-check untuk `backend/app/services/auth` dan repository yang sudah ditargetkan
- pytest
- Alembic migration smoke test ke MySQL
- MySQL integration test (pipeline lock + rollback retention)
- benchmark regression gate
- concurrency smoke test
- concurrency failure scenario (expected fail-path)
- observability payload smoke test
- non-functional triage summary artifact (`nonfunctional_triage.md`)
- weekly SLA baseline artifact (`weekly_sla_baseline.md` + `.json`)
- Docker build backend dan dashboard
- pip-audit untuk backend/dashboard dependencies
- Bandit + Semgrep SAST
- Gitleaks secret scan

Catatan developer velocity:
- `actions/setup-python` di workflow CI sudah mengaktifkan `cache: pip` untuk mempercepat install dependency di tiap job.
- Workflow CI juga dijadwalkan mingguan (setiap Senin UTC) untuk menghasilkan baseline SLA report dari artifact smoke terbaru.

### Triage gate non-functional

Jika job `non-functional-smoke` gagal:
- Download artifact `non-functional-smoke-artifacts`.
- Buka `nonfunctional_triage.md` sebagai template triage standar run tersebut.
- Cek `benchmark.json`: endpoint mana dengan `p95_ms`/`max_ms` tertinggi dan apakah melebihi threshold.
- Cek `concurrency.json`: lihat endpoint dengan `failures` non-empty atau latency outlier.
- Cek `observability_payload.json`: lihat `missing_requests` dan `missing_rows`.
- Cek `uvicorn.log` untuk error backend saat benchmark/smoke berjalan.

Generate manual report dari artifact lokal:

```bash
python scripts/nonfunctional_report.py --artifacts-dir .ci_artifacts --triage-output .ci_artifacts/nonfunctional_triage.md --sla-output .ci_artifacts/weekly_sla_baseline.md --sla-json-output .ci_artifacts/weekly_sla_baseline.json
```

## Operasional Harian

### Cek service

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl -H "x-api-key: dev-internal-key" http://localhost:8000/observability/summary
```

### Cek metrics Prometheus-style

```bash
curl -H "x-api-key: dev-internal-key" http://localhost:8000/observability/metrics
```

Untuk payload observability endpoint paged, cek metrik:
- `network_monitoring_api_payload_requests_total`
- `network_monitoring_api_payload_rows_total`
- `network_monitoring_api_payload_total_rows_sum`
- `network_monitoring_api_payload_sampled_total`

### Jalankan manual cycle

```bash
curl -X POST http://localhost:8000/system/run-cycle -H "x-api-key: dev-internal-key"
```

Jika mendapat `409 Conflict`, berarti monitoring pipeline sedang berjalan.

### Lihat log Docker

```bash
docker compose logs --tail=100 backend
docker compose logs --tail=100 scheduler
docker compose logs --tail=100 dashboard
```

### Apply migration setelah deploy

```bash
docker compose --profile ops run --rm migrate
docker compose up -d --build
```

## Troubleshooting

### Backend gagal startup di production

Cek env berikut:
- `AUTH_PASSWORD_SECRET`
- `AUTH_JWT_SECRET`
- `INTERNAL_API_KEY` atau `INTERNAL_API_KEYS`
- `BOOTSTRAP_ADMIN_PASSWORD`
- `CORS_ORIGINS`
- `TRUSTED_HOSTS`
- `AUTH_COOKIE_SECURE`

Production akan fail-fast jika konfigurasi security longgar.

### Dashboard login gagal

Cek:
- backend hidup di `DASHBOARD_API_URL`
- browser bisa akses `DASHBOARD_PUBLIC_API_URL`
- `CORS_ORIGINS` mengizinkan URL dashboard
- `TRUSTED_HOSTS` mengizinkan host backend
- admin bootstrap sudah dibuat
- password memenuhi policy

### Endpoint API return 401

Gunakan salah satu:
- header `Authorization: Bearer <token>`
- header `x-api-key: <secret>`

Untuk endpoint write/ops, pastikan role/scope benar.

### Scheduler degraded

Cek:
- `GET /health/dependencies`
- `GET /observability/summary`
- log service `scheduler`
- koneksi DB
- interval scheduler dan timeout collector

Job failure beruntun akan muncul sebagai operational alert.

### Metric kosong

Cek:
- device `is_active=True`
- `device_type` sesuai collector
- scheduler worker jalan
- manual `POST /system/run-cycle`
- ping/SNMP/RouterOS credentials benar
- database migration sudah head

### Printer SNMP tidak muncul

Cek:
- device type `printer`
- printer bisa diping
- SNMP v2c aktif di printer
- community masuk di `PRINTER_SNMP_COMMUNITIES`
- port UDP 161 tidak diblok
- coba `scripts/test_snmp.py`

### Mikrotik API gagal

Cek:
- `MIKROTIK_HOST`, `MIKROTIK_PORT`, `MIKROTIK_USERNAME`, `MIKROTIK_PASSWORD`
- service API RouterOS aktif
- firewall Mikrotik mengizinkan koneksi dari host scheduler
- metric `mikrotik_api` di latest snapshot

### Data history terlalu besar

Cek:
- `RAW_METRIC_RETENTION_DAYS`
- `RETENTION_ROLLUP_BATCH_SIZE`
- `RETENTION_ARCHIVE_BATCH_SIZE`
- job `retention_cleanup`
- tabel `metric_daily_rollups` dan `metric_cold_archives`

## Catatan Deployment

- Compose publish MySQL, backend, dan dashboard ke `127.0.0.1` agar tidak terbuka ke LAN secara tidak sengaja.
- Backend dan dashboard container berjalan sebagai non-root user.
- Backend bisa multi-worker lewat `WEB_CONCURRENCY`.
- Migration adalah step eksplisit, bukan bagian startup backend/scheduler.
- Untuk reverse proxy, isi `TRUSTED_PROXY_IPS` agar `X-Forwarded-For` hanya dipercaya dari proxy yang dikontrol.
- Simpan secret production di secret manager atau environment deployment, bukan di git.

## Security Scan Dan Rotasi Key

CI menjalankan security scan berikut:
- `pip-audit` untuk dependency vulnerability Python.
- `bandit` untuk SAST Python backend + script ops.
- `semgrep` untuk ruleset security tambahan.
- `gitleaks` untuk deteksi kebocoran secret di git history.

Checklist rotasi key production (berkala, minimal per 90 hari):
1. Generate key baru untuk `AUTH_JWT_SECRET`, `AUTH_PASSWORD_SECRET`, dan API key internal.
2. Simpan key baru di secret manager / file secret runtime (jangan commit ke git).
3. Deploy dengan dual-key window jika dibutuhkan (tambahkan key baru dulu, lalu cutover traffic).
4. Restart backend + scheduler terkontrol, lalu verifikasi login, refresh session, dan endpoint internal.
5. Revoke key lama, hapus file secret lama, dan catat waktu rotasi di runbook.
6. Jalankan smoke check: `/health/ready`, `/health/dependencies`, `/observability/summary`, serta alur login dashboard.

## Posisi Streamlit

Dashboard Streamlit di project ini diposisikan sebagai frontend internal ops, bukan public web app multi-user skala besar.

Masih cocok untuk:
- dashboard internal tim kecil
- troubleshooting harian
- auto-refresh ringan
- pagination/filter server-side

Mulai tidak ideal jika:
- banyak user aktif bersamaan
- UX semakin kompleks dan stateful
- butuh realtime interaktif yang lebih presisi
- auth/navigation perlu kontrol frontend penuh

Kalau kebutuhan sudah menuju sana, jalur upgrade paling aman adalah mempertahankan FastAPI sebagai backend observability dan mengganti dashboard menjadi frontend web dedicated.

## Checklist Handover

Sebelum project diserahkan ke maintainer baru:
- pastikan `.env.example` sesuai target environment
- berikan credential admin awal lewat channel aman
- jelaskan hostname backend/dashboard yang dipakai browser
- jalankan `alembic upgrade head`
- jalankan `python -m pytest`
- jalankan satu `POST /system/run-cycle`
- cek `/health/ready`, `/health/dependencies`, dan `/observability/summary`
- pastikan scheduler worker hidup
- pastikan device inventory sudah benar
- pastikan threshold sesuai standar operasional
- pastikan Telegram, SNMP printer, dan Mikrotik credentials sudah diuji bila fitur itu dipakai

## Perintah Cepat

```bash
# Test
python -m pytest

# Lint
ruff check backend dashboard scripts tests

# Type check
mypy backend scripts
pyright

# Security scan (dependency + SAST + secret)
pip-audit -r requirements/backend.txt
pip-audit -r requirements/dashboard.txt
bandit -q -r backend scripts -x tests,venv
semgrep scan --config p/security-audit --config p/python --error --metrics=off --exclude venv --exclude tests backend scripts dashboard
gitleaks detect --source . --no-git

# Backend lokal
uvicorn backend.app.main:app --reload

# Scheduler lokal
python -m backend.app.scheduler.worker

# Dashboard lokal
streamlit run dashboard/Overview.py

# Migration
alembic upgrade head

# Docker migration
docker compose --profile ops run --rm migrate

# Docker full stack
docker compose up --build
```
