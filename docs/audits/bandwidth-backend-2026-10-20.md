# Audit backend bandwidth — 20 Oktober 2026

## Ruang lingkup

Domain flow, entrypoint runtime, settings, Compose, policy lokal, health,
repository/service ingestion dan rekonsiliasi, dokumentasi dan deployment aktif.
Perubahan fitur/UI/notifikasi lain yang sudah ada di working tree dipertahankan.
Tidak ada migrasi schema, penghapusan data atau perubahan kebijakan klasifikasi.

## Temuan dan perbaikan

| Temuan | Dampak | Perbaikan |
| --- | --- | --- |
| Inventory CLI membaca raw `os.environ`, berbeda dari settings `.env` | CLI lokal bisa mengabaikan target, host dan polling dari file env | Tiga field inventory ditambahkan ke `Settings`; CLI memakai default typed yang sama, argumen eksplisit tetap override |
| Health ingestion hanya memberi batas bawah heartbeat | Timestamp masa depan bisa terlihat sehat; berbeda dari diagnostics/inventory | Kontrak freshness murni bersama; future/stale ditolak, stream/router/policy diverifikasi |
| Env/database/build/mount worker diulang di overlay | Perubahan salah satu service bisa menimbulkan drift | Anchor Compose bersama; deployment canonical `docker-compose.bandwidth.yml` |
| File deployment aktif bernama example | Sulit membedakan template dan konfigurasi operasional | Nama canonical baru; nama lama hanya symlink kompatibilitas, hasil resolve service/volume terbukti setara |
| Contoh env tidak mencantumkan semua input deployment | Router/listener/policy host/image harus ditebak dari catatan chat | `.env.example` lengkap; tabel membedakan env deployment, path host dan path runtime |
| Profil LAN/VPN aktif tersebar di `goflow2/` | Salah memilih policy setelah pindah jaringan | Satu `flow-policy.local.json` aktif; digest tidak berubah; profil lama dipindahkan ke backup privat |
| Runbook memuat status tahap lama yang bertentangan | Instruksi mengatakan rekonsiliasi/UI belum ada padahal sudah aktif | Panduan utama ringkas, penerimaan generik, arsip eksperimen terpisah, tautan diperbarui |

## Verifikasi

- Backend cepat: 404 lulus, 3 khusus MySQL dilewati, 148 deselected.
- MySQL disposable: 23 lulus untuk config, health, inventory, rekonsiliasi dan
  validasi transfer; termasuk future heartbeat, .env defaults/CLI override,
  replay, rollback, isolasi router, serta konservasi byte.
- Ruff lint/format dan mypy modul berubah lulus, dengan versi requirements/dev.txt.
- Compose canonical dan alias resolve ke service dan volume identik; dependency
  collector healthy sebelum worker, mount policy dan UDP 2055 diverifikasi.
- Image backend/worker dibangun dan runtime dipasang; collector 2055 tetap hidup.
- Worker/inventory membaca policy canonical dengan digest yang sama. Semua
  layanan terkait sehat, receipt baru masuk, pending nol; API daily/clients 200.
- Total raw upload/download sama persis dengan total daily pada snapshot DB live;
  revisi schema tetap `20261015_0033`.

Warning deprecation Starlette/httpx pada test suite existing tetap ada dan tidak
berasal dari perubahan audit ini. Frontend tidak berubah pada audit backend.

## Batas audit dan tindak lanjut

Retention otomatis raw flow/checkpoint dan histori identitas belum tersedia.
Penghapusan ad-hoc berisiko merusak rekonsiliasi/audit; perlu rancangan retention
serta validasi restore tersendiri. Volume stream historis dipertahankan, bukan
dianggap sampah hanya karena muncul warning label Compose.

Uji transfer upload/download berukuran diketahui dan pengukuran kehilangan/duplikasi
UDP masih diperlukan untuk penerimaan operasional. Status completeness tetap
unverified. Tidak ada perubahan router, port, subscriber notifikasi, atau volume
stream aktif selama audit ini.

## Addendum: automatic LAN/VPN transport

- Collector host binding now `0.0.0.0:2055/udp`, independent of changing Mac IPv4.
- Inventory tries VPN `10.10.10.1:8331`, then LAN `192.168.1.1:8728` each poll.
  Both endpoints use the existing Head Office credentials/binding and require
  exact router identity `Rtr.UTAMA SSKB`. Port overrides are optional, typed,
  bounded and CLI-overridable; empty values preserve existing target ports.
- Optional explicit exporter aliases keep source validation bounded to reviewed
  IPv4 addresses. Legacy policy digests remain unchanged without aliases.
  Adding aliases requires a fresh stream; local auto volume is
  `network_monitoring_bandwidth_ho_auto_v1`, stream
  `5bd68fdd-1aad-400d-b32f-9c4352d86f83`. Previous LAN spool had zero ready/open
  segments at cutover; historical volumes and private config backups retained.
- Verified 153 bandwidth tests, 3 environment-specific skips; 22 isolated MySQL
  tests passed. Ruff for changed bandwidth modules/tests and mypy for both
  changed runtime modules pass. Existing `core/config.py` B018 finding at the
  MikroTik validation property remains outside these additions.
- Live fallback verified: VPN API 8331 timed out; LAN snapshot committed 73/74
  clients after identity validation, inventory healthy. All six application /
  bandwidth containers healthy. Accepted flow count 362637, receipt about two
  seconds old, pending segments zero; no new unexpected exporter rejections.
- VPN API success and actual offsite LAN-to-VPN transition remain unverified
  until the router permits API 8331 and its Traffic Flow target points to the
  Mac's current VPN IP. The project does not change router settings or infer
  full bandwidth completeness from container health.
