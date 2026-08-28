# Internal Module Ownership

Dokumen ini adalah peta singkat untuk perubahan internal. Kontrak HTTP tetap berada di FastAPI; Streamlit hanya memanggil API dan merender state.

| Area | Lokasi utama | Ownership dan batas perubahan |
| --- | --- | --- |
| Collector | `backend/app/monitors/` | Collector mengembalikan metric payload dan collection status aman. Gunakan `monitors/contracts.py` untuk taxonomy status; jangan log credential atau raw packet. |
| Alerting | `backend/app/alerting/engine_parts/` | Rule evaluator menentukan expected alert; `impl.py` hanya mengorkestrasi lifecycle, incident, dan notifier. Tambah rule beserta fixture unitnya. |
| Database | `backend/app/models/`, `backend/app/repositories/`, `alembic/` | Perubahan schema wajib memiliki migration upgrade/downgrade dan lulus migration gate. |
| API/service | `backend/app/services/`, `backend/app/api/` | Authorization, shaping payload, dan business logic berada di sini. Dashboard tidak boleh menduplikasi policy. |
| Dashboard | `dashboard/pages/`, `dashboard/components/` | Rendering, state filter, pagination, export, dan action API. Reuse helper komponen sebelum menambah formatter/pagination baru. |

## Contract collector

`collection_status` hanya memakai: `ok`, `timeout`, `authentication_failed`, `connection_failed`, `unsupported_oid`, `protocol_error`, `invalid_response`, `rate_limited`, `configuration_missing`, atau `collector_error`.

Status collector menjelaskan apakah data dapat dikumpulkan; status hardware/target tetap disimpan pada metric bisnis seperti `ping`, toner, volume, atau service HTTP. Alert collector yang tidak sehat harus menekan alert bisnis yang bergantung pada data invalid.

## Menambah vendor atau rule

1. Tambahkan adapter collector di domain yang relevan dan gunakan contract status pusat.
2. Tambahkan metric label serta empty/error state Live Monitoring bila metric baru user-facing.
3. Tambahkan rule evaluator, primary metric mapping, dan test yang tidak membutuhkan jaringan nyata.
4. Bila schema berubah, tambahkan migration lalu jalankan migration gate.
