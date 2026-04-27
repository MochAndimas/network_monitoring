# Release, Versioning, dan Changelog Policy

Project ini mengikuti:
- Semantic Versioning (`MAJOR.MINOR.PATCH`)
- Keep a Changelog format

## Versioning Rules

1. `PATCH`:
- bug fix
- perbaikan non-breaking internal
- hardening yang tidak mengubah kontrak API

2. `MINOR`:
- fitur baru yang backward compatible
- endpoint baru tanpa menghapus endpoint lama

3. `MAJOR`:
- perubahan breaking pada kontrak API/behavior utama
- penghapusan endpoint/fitur tanpa backward compatibility

## Release Cadence

1. Default: rolling release via branch `main/master`.
2. Buat release tag untuk milestone stabil:
- contoh: `v1.3.0`

## Changelog Discipline

1. Semua PR yang mengubah behavior harus update `CHANGELOG.md` pada bagian `Unreleased`.
2. Kategori minimal:
- `Added`
- `Changed`
- `Fixed`
- `Security`
3. Saat cut release:
- pindahkan item `Unreleased` ke section versi baru + tanggal rilis.

## Definition of Done (Release Readiness)

Sebelum rilis:
1. `ruff check backend dashboard scripts tests` pass.
2. `mypy --config-file mypy.ini` dan `pyright` pass.
3. `pytest -q` pass.
4. Migration sudah diverifikasi (`alembic upgrade head`).
5. Changelog ter-update.
6. Jika ada perubahan operasional/security, runbook dan README ikut diupdate.
