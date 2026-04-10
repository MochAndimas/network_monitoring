# Network Monitoring MVP

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

5. Jalankan migration database

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

## Menjalankan Backend

```bash
uvicorn backend.app.main:app --reload
```

API utama:
- `GET /dashboard/summary`
- `GET /devices`
- `POST /devices`
- `PUT /devices/{device_id}`
- `GET /metrics/history`
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

Kalau database baru pertama kali dijalankan, tetap jalankan migration:

```bash
alembic upgrade head
```

Dashboard utama sekarang bisa:
- melihat summary status internet, server, Mikrotik, dan alert aktif
- trigger manual monitoring cycle
- melihat daftar device dan filter berdasarkan type
- melihat alert aktif
- melihat incident aktif/resolved
- melihat histori metric dan chart untuk metric numerik
- melihat dan mengubah threshold alert

## Testing

```bash
python -m pytest tests/api/test_dashboard_endpoints.py
```

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
- Jika `INTERNAL_API_KEY` diisi, endpoint mutasi seperti `POST /devices`, `PUT /devices/{device_id}`, `PUT /thresholds/{key}`, dan `POST /system/run-cycle` akan meminta header `x-api-key`
- Endpoint `GET /health` dan `GET /observability/summary` bisa dipakai untuk readiness check dan ringkasan operasional
