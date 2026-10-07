# Changelog

All notable changes to this project will be documented in this file.

Format mengacu ke [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
dan project ini mengikuti [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- Kolom tabel Auth Observability/Runtime dapat menyusut pada layar kecil agar System Health tidak melebar di luar viewport.
- Badge inventory “Aktif dipantau” dan “Tidak aktif” menggunakan total dan jumlah perangkat aktif dari API, termasuk perangkat tanpa metrik; kontrak status-only dashboard tetap dipertahankan.

### Added
- Menambahkan runbook operasional untuk backup/restore DB, DR drill, incident response SOP, dan SLO alerting actionability di `docs/ops/runbook.md`.
- Menambahkan DX tooling standar:
  - `.pre-commit-config.yaml`
  - `justfile`
  - `Makefile`
- Menambahkan policy release/versioning/changelog di `docs/release-policy.md`.

### Changed
- Sidebar desktop menampilkan ikon saat tidak di-hover dan membuka label saat hover atau fokus keyboard.
- Menyamakan default retention `RAW_METRIC_RETENTION_DAYS` di `docker-compose.yml` menjadi `7` hari agar konsisten dengan konfigurasi aplikasi.
- Mengubah `requirements.txt` root menjadi entrypoint dependency runtime (`requirements/backend.txt` + `requirements/dashboard.txt`) agar tidak membingungkan pengguna baru.

### Security
- Hardening cookie-based auth flow dengan validasi origin/host untuk request berbasis cookie (`/auth/restore` dan jalur cookie di `/auth/logout`).
