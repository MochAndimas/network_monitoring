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
- PostgreSQL
- SQLAlchemy
- APScheduler
- Streamlit
- psutil
- ping3
- librouteros

## Struktur Utama
- `backend/app/main.py`: boot FastAPI, init DB, start scheduler
- `backend/app/monitors/*`: internet, device, server, Mikrotik checks
- `backend/app/alerting/*`: evaluasi alert, notifier, incident lifecycle
- `backend/app/api/routes/*`: endpoint dashboard, devices, metrics, alerts, incidents, system
- `dashboard/*`: Streamlit UI
- `scripts/bootstrap_demo.py`: seed device + jalankan satu monitoring cycle
- `scripts/run_monitor_cycle.py`: trigger satu monitoring cycle manual

## Persiapan

1. Buat dan aktifkan virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate
```

2. Install dependency

```bash
python -m pip install -r requirements.txt
```

3. Siapkan environment file

```bash
copy .env.example .env
```

4. Jalankan PostgreSQL

```bash
docker compose up -d postgres
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

## Menjalankan Backend

```bash
uvicorn backend.app.main:app --reload
```

Endpoint mutasi membutuhkan header `x-api-key` saat `INTERNAL_API_KEY` terisi. Di `APP_ENV=production`,
`INTERNAL_API_KEY` wajib diisi dan request mutasi akan ditolak kalau key belum tersedia.

API utama:
- `GET /dashboard/summary`
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
- `PUT /thresholds/{key}`
- `POST /system/run-cycle`

## Menjalankan Dashboard

```bash
streamlit run dashboard/Overview.py
```

## Menjalankan Dengan Docker Compose

Build dan jalankan seluruh stack:

```bash
docker compose up --build
```

Service default:
- PostgreSQL di `localhost:5432`
- FastAPI backend di `http://localhost:8000`
- Streamlit dashboard di `http://localhost:8501`

Saat backend container start, entrypoint menjalankan `alembic upgrade head` otomatis sebelum Uvicorn.
Compose juga memakai healthcheck: backend menunggu PostgreSQL sehat, dashboard menunggu backend sehat,
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
- Set `APP_ENV=production` dan isi `INTERNAL_API_KEY` dengan nilai random panjang di setiap deployment.
- Dashboard mengirim header `x-api-key` otomatis kalau `INTERNAL_API_KEY` tersedia di environment.
- `.env` masuk `.gitignore`; simpan secret production di secret manager atau environment deployment.

## Testing

```bash
python -m pytest
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

## Migration

Generate migration baru setelah schema berubah:

```bash
alembic revision --autogenerate -m "describe change"
```

Apply migration terbaru:

```bash
alembic upgrade head
```

## Catatan Implementasi
- Scheduler berjalan otomatis saat backend start, kecuali `SCHEDULER_ENABLED=false`
- Monitor internet/device memakai `ping3`
- Monitor server memakai `psutil` untuk CPU, memory, disk, dan boot time
- Monitor Mikrotik mencoba akses RouterOS API jika kredensial di `.env` tersedia
- Alert aktif akan menghasilkan incident aktif per device
- Threshold alert disimpan di database dan otomatis dibuat saat belum ada
- Endpoint mutasi seperti `POST /devices`, `PUT /devices/{device_id}`, `PUT /thresholds/{key}`, dan `POST /system/run-cycle` memakai header `x-api-key`
- Endpoint `GET /health` dan `GET /observability/summary` bisa dipakai untuk readiness check dan ringkasan operasional

## Checklist Arsitektur
- Backend API, DB session, dan HTTP outbound utama sudah async-friendly.
- Library blocking seperti `ping3`, `psutil`, dan `librouteros` diisolasi lewat `asyncio.to_thread`.
- Monitoring cycle berjalan paralel dengan session terpisah per runner, lalu persist dan evaluasi alert di fase akhir.
- Scheduler dan manual run-cycle sudah punya guard supaya tidak overlap.
- Endpoint list besar yang dipakai dashboard sudah punya versi paged untuk menjaga performa saat data tumbuh.
- Retention rollup sudah diproses secara streaming agar tidak memuat semua raw metric lama ke memory sekaligus.
- Dashboard Streamlit tetap model sinkron, jadi optimasi difokuskan ke query server-side, pagination, dan pengurangan kerja dataframe di client.
