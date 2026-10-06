# IMP-010 — Modul dan kontrak pengujian

Tanggal: 2026-10-01. Status: selesai untuk implementasi, pengujian dan deployment lokal.

## Struktur dan keputusan

- `engine_parts/impl.py` mengorkestrasi evaluasi. `evaluation_inputs.py` menangani
  snapshot/history/freshness/maintenance; `lifecycle.py` menangani alert/incident;
  `notification_queries.py` menangani query history Telegram; `legacy_delivery.py`
  menampung jalur pengiriman historis. Policy dan formatting tetap modul terpisah.
- `metric_history_service.py`, `metric_snapshot_service.py`, `metric_summary_service.py`
  memisahkan use case read. Helper cursor, section dan payload dipakai bersama.
  `metrics_read_service.py` mempertahankan import publik API tanpa mengubah respons,
  pagination, sampling, batas data atau query repository.
- Devices memisahkan `use-device-filters` dan `use-device-management`; form/import
  tetap komponen tersendiri. Accounts memisahkan hook admin, hook akun sendiri, form
  dan rendering viewer. Query frontend meneruskan AbortSignal.
- Formatter Prettier 3.6.2 dipin untuk kedua feature dan diperiksa di Makefile/CI.
  File format-only tetap mempertahankan perilaku sebelumnya.
- `AlertEvaluationDependencies` bersifat frozen/per-call: clock, repository factories,
  expected-alert loader, policy dan sender. Pemanggil operasional mengimpor orchestrator
  langsung melalui service outbox. Facade lama meneruskan sender per-call; tidak lagi
  mengganti global sender impl. Simbol privat historis masih tersedia selama migrasi.
- Collector menerima runner dan session factory; persistence menerima repository factory.
  TelegramNotifier menerima config dan async transport berkontrak, dengan hasil/log aman.
  Dependency default tetap memakai konfigurasi runtime dan session operasional yang sama.
- `shared/metric_contracts.py` mendefinisikan MetricWritePayload. Repository menerima
  payload bertipe maupun Mapping legacy. Perbaikan perilaku yang disengaja: nilai numeric
  eksplisit tidak menyebabkan keyword ganda pada konstruktor Metric; nol/None dipertahankan.
- Tes outbox/lifecycle menggunakan dependency per-call untuk expected alerts/sender/clock.
  Tes rolling history memakai modul penanggung jawab dan waktu eksplisit. Reset dictionary
  dedupe inert di tes API dihapus. Migrasi test/facade dilakukan bertahap, bukan penghapusan
  semua monkeypatch atau simbol privat dalam seluruh codebase.

## Validasi

| Pemeriksaan | Hasil |
| --- | --- |
| `make backend-check` (venv proyek) | 386 lulus; 22 tes MySQL terpisah dilewati |
| Ruff lint/staged + formatting | Lulus; 239 file Python terformat |
| mypy dan Pyright | Lulus, tanpa error/warning tipe |
| Bandit backend/scripts | Lulus |
| Alembic upgrade head + check pada MySQL 8.4 fixture | Lulus; tidak ada schema drift |
| `pytest tests/services/test_mysql_integration.py -q` pada fixture | 22 lulus |
| `make frontend-check` | Formatting, ESLint, TypeScript, 40 tes/17 file dan build lulus |
| Compose build backend/scheduler/notification-worker/frontend | Lulus |
| Health lokal | Backend/frontend/worker healthy; scheduler running; readiness scheduler up |
| Browser setelah rebuild | Devices manage memuat 38 inventory dan 10 baris/halaman; Accounts memuat 2 akun |

Tes baru membuktikan clock mengontrol create/resolve alert dan incident, session collector
terpisah dari session persist, numeric nol masuk raw/latest, transport Telegram menghasilkan
accepted/failed/unconfigured tanpa bocor token, role viewer tidak membaca daftar admin,
edit akun tidak mengirim password, state reset password dibersihkan, save device menutup
form dan perubahan filter/unmount membatalkan request lama. Transport tes adalah mock;
tes ini tidak mengirim Telegram atau memodifikasi akun/perangkat operasional.

Verifikasi MySQL menemukan fixture tie-order memakai mikrodetik, sementara DATETIME(0)
membulatkan pecahan detik ke atas. Akibatnya dua sampel terbaru sesekali berada di luar
checked_to. Fixture sekarang memakai presisi detik yang sama dengan schema; assertion
urutan ID dan scope tidak dilonggarkan. Probe fixture membuktikan .900000 dibulatkan
ke detik berikutnya. Semua 22 tes lulus setelah koreksi.

Fixture MySQL terisolasi memakai port 13330/database imp010_validation_fixture dan telah
dihentikan setelah pengujian. Migrasi tidak menambah revision untuk refactor ini.

## Batas hasil

- Refactor mempertahankan aturan alert, transaksi/outbox, ownership collector dan kontrak
  API. Tidak ada klaim kapasitas perangkat baru dari perubahan struktur modul.
- Compatibility facade tetap ada agar migrasi caller/test dapat berlanjut tanpa breakage.
- Build lokal mencatat warning Autoprefixer lama tentang nilai CSS `end`; build tetap lulus.
  Suite backend mencatat satu deprecation Starlette/httpx pada test client.
- Pemeriksaan browser merupakan smoke read-only pada Devices/Accounts, bukan seluruh
  suite E2E browser. Mutation diuji pada mock/fixture; tidak dilakukan CRUD operasional.
- Badge inventory `active` masih mengikuti implementasi sebelum refactor: UI membaca
  field active yang tidak disediakan endpoint status-summary. Ini temuan UI terpisah;
  smoke tidak dipakai untuk menyatakan seluruh angka badge benar.

## Tindak lanjut 2026-10-06

Temuan badge di atas ditutup: endpoint `/devices/status-summary` menambahkan
`total` dan `active` dari inventory, termasuk device tanpa metrik. Kontrak repository
status-only untuk dashboard tetap sama. Regression test mencakup perangkat aktif,
nonaktif, tanpa metrik, dan filter `active_only`. Respons operasional setelah rebuild
backend: total 38, active 38, up 37, down 1.

Validasi ulang: 387 tes backend non-MySQL dan 40 tes frontend lulus; lint,
format, mypy, Pyright, Bandit, pip check dan build produksi lulus.
E2E menemukan overflow pada grid Auth Observability/Runtime; `min-width: 0`
pada anak `.two-column` mengizinkan scroll tabel tetap berada dalam halaman.
Deployment lingkungan lain ditunda atas arahan pengguna karena target belum tersedia.

Enam skenario E2E fungsional lulus pada Chromium dengan frontend production dan
backend SQLite fixture terpisah (port 13000/18000). Fixture dimatikan dan database
sementara dihapus setelah run. Visual baselines dan CRUD operasional tidak dijalankan;
22 tes MySQL tidak diulang pada tindak lanjut ini. Run CI remote baru belum dijalankan.
