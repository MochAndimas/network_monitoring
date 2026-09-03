# Network Monitoring

Network Monitoring adalah aplikasi observabilitas jaringan dengan backend FastAPI, scheduler/collector Python, MySQL, dan dashboard Next.js.

## Komponen

- `frontend/` — dashboard Next.js pada `http://localhost:3000`.
- `backend/` — API FastAPI pada `http://localhost:8000`.
- `scripts/` — bootstrap, migrasi, dan utilitas operasional.
- `alembic/` — migrasi database.

## Menjalankan lokal

Siapkan `.env` dari `.env.example`, lalu isi seluruh secret wajib, khususnya database, auth, bootstrap admin, CORS, dan trusted hosts.

```sh
docker compose up -d --build
```

Layanan utama:

- Dashboard: `http://localhost:3000`
- API: `http://localhost:8000`

Untuk menjalankan frontend tanpa Docker:

```sh
cd frontend
pnpm install
pnpm dev
```

## Validasi

```sh
cd frontend
pnpm typecheck
pnpm test
pnpm build
```

E2E memakai Playwright dan hanya boleh dijalankan pada environment fixture dengan kredensial test. Lihat `frontend/e2e/README.md`.

## Keamanan

- Jangan menyimpan secret di repository.
- Batasi `CORS_ORIGINS` ke origin dashboard yang digunakan.
- Jalankan mutation E2E hanya pada fixture terisolasi.
