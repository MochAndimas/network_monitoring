# Audit dan rencana integrasi penggunaan internet per perangkat

> Riwayat implementasi bertahap. Untuk konfigurasi dan status operasional,
> gunakan [panduan bandwidth](ops/bandwidth.md), bukan instruksi tahap lama.

Tanggal audit: 15 Oktober 2026. Status: rancangan berdasarkan source code dan daftar container lokal; belum ada implementasi atau perubahan konfigurasi router.

## Pembaruan aktivasi 19 Oktober 2026

Head Office telah dipindahkan ke collector project melalui OpenVPN. Sumber asli
UDP 10.10.10.1→10.10.10.42 terbukti melalui capture Mac. Policy mengikuti sampler
gateway Compose yang terverifikasi, bukan alamat sumber collector manual; stream
awal yang ditolak dipertahankan dan stream baru memakai volume lokal terpisah.
Flow upload/download nyata tersimpan, total raw dan agregasi harian cocok, serta
endpoint terautentikasi daily/top dan UI merespons 200. Snapshot API mencatat 105
perangkat. Poller inventory opsional satu router ditambahkan untuk pembaruan
identitas tanpa menjalankan scheduler alert atau notification worker.

GoFlow2 batch separator kosong kini diabaikan oleh supervisor; record malformed
nonkosong tetap diukur. Tes CLI/ingestion MySQL terisolasi 19 lulus; tes inventory
worker MySQL 3 lulus. Detail deployment, batas atribusi dan rollback ada di
`docs/ops/bandwidth-acceptance.md`. Tahap keenam masih memerlukan transfer terukur
dari LAN kantor; penerimaan operasional penuh belum dinyatakan selesai.
Suite backend final 393 lulus (2 khusus MySQL dilewati, 148 deselected). Collector
stdout menggunakan satu decoder worker setelah ditemukan record JSON menempel
pada output paralel. Verifikasi terakhir: 38.445 accepted flow, pending nol,
inventory 107 perangkat, 59 baris top usage teridentifikasi, semua service terkait
sehat. Scheduler umum dan notification worker tetap tidak dinyalakan.

## Pembaruan implementasi tahap pertama

Modul offline `backend/app/bandwidth/` sudah menyediakan kontrak immutable,
normalisasi IPFIX/NAT IPv4 dan klasifikasi berdasarkan policy per router.
Konfigurasi subnet, interface dan pengecualian remote diberikan caller; tidak
tergantung global settings atau session database. Alasan penolakan tersedia
sebagai enum untuk counter worker pada tahap berikutnya.

Validasi: 58 test bandwidth dan 11 test regresi konfigurasi/status collector
MikroTik lulus (69 total). Ruff lint/format dan mypy modul baru juga lulus.
Kasus mencakup NAT hex/dotted, download routed, input invalid, isolasi router,
traffic yang dikecualikan, nanodetik presisi, pergantian hari dan flow terlambat.

Belum ada ingestion live, alokasi byte per hari, deduplikasi, migrasi database,
sinkronisasi identitas atau UI baru. Tidak ada perubahan konfigurasi router/container.
Contoh penggunaan dan batas kontrak tersedia di `backend/app/bandwidth/README.md`.

## Pembaruan implementasi tahap kedua

Inventaris klien dan histori observasi IP sudah diimplementasikan dengan tiga
tabel MySQL, migrasi `20261015_0031`, repository dan service transaksional.
Collector memakai ulang DHCP/ARP dan membawa snapshot ke transaksi penyimpanan
metrik pada scheduler maupun run manual. Tersedia flag default nonaktif,
penanganan replay/stale snapshot, konflik MAC, pergantian IP, gap observasi dan
resolver yang menolak atribusi tanpa cakupan waktu yang cukup.

Validasi tahap kedua:

- Suite backend cepat: 340 lulus, 1 dilewati (row-lock MySQL), 148 deselected.
- Setelah tambahan test integrasi flag collector: 22 test inventaris/collector/
  migrasi SQLite lulus, 1 test row-lock dilewati.
- Suite inventaris final pada MySQL 8.4 disposable: 20 lulus, termasuk concurrency
  REPEATABLE READ, rollback, dan integrasi flag collector.
- Gate MySQL final: satu head, seluruh upgrade dari kosong, `alembic check`,
  downgrade kosong ke `20260923_0030`, upgrade ulang dan check kedua lulus.
- Lint/format kode baru, typecheck tujuh modul terkait dan diff whitespace lulus.

Belum menjalankan migrasi atau aktivasi pada database project/router. Tahap
selanjutnya adalah spool/worker ingestion IPFIX dan penyimpanan byte flow;
inventaris ini belum menghasilkan angka penggunaan harian atau UI bandwidth.
Panduan aktivasi dan batas kualitas identitas: `docs/ops/bandwidth-inventory.md`.

## Pembaruan implementasi tahap ketiga

Ingestion opsional sudah tersedia: supervisor GoFlow2 stdout, spool sealed dengan
fsync/checksum, worker batch dan migrasi `20261015_0032`. Flow, rejection counters
dan checkpoint byte berada dalam satu transaksi. File spool dihapus hanya setelah
commit seluruh segmen; replay posisi yang sama tidak memasukkan flow ulang.
Lookup histori IP dilakukan secara batch, sementara flow tanpa coverage identitas
tetap tersimpan dengan client NULL.

Mapping project kini mempertahankan `sampler_address` dan `sequence_num`.
Policy per stream memverifikasi exporter/router dan tidak boleh berubah sesudah
registrasi. Tersedia heartbeat, retry DB dengan backoff, deteksi pending segment
yang hilang, kapasitas spool tanpa eviction, recovery crash dan shutdown/drain.

Validasi tahap ketiga:

- Suite backend cepat: 366 lulus, 2 test row-lock MySQL dilewati, 148 deselected.
- Verifikasi fokus source final: 25 test spool/ingestion/migrasi lulus dan 1
  row-lock MySQL dilewati, termasuk guard binding router saat spool idle.
- MySQL 8.4 disposable: 30 test inventory/ingestion lulus, mencakup replay,
  rollback, batas batch, integer presisi dan concurrent REPEATABLE READ.
- Migrasi dari kosong melalui `0032`, check schema, downgrade kosong ke `0031`,
  upgrade dan check ulang lulus; satu Alembic head.
- Image collector source final berhasil dibangun. Satu datagram IPFIX sintetis
  dengan dua record berhasil didecode GoFlow2 menjadi spool sealed, total 8.356
  byte dengan field NAT/exporter yang sesuai. Tidak memakai traffic router kantor.
- Compose overlay tervalidasi tanpa menjalankan deployment; lint/format, mypy
  13 modul dan whitespace diff lulus.

Jaminan replay berlaku pada posisi spool, bukan deduplikasi datagram UDP atau
jaminan seluruh traffic tertangkap. Belum ada agregasi harian, rekonsiliasi
identitas tertunda, retensi flow DB otomatis, API/UI bandwidth maupun alert
ingestion di System Health. Runtime tetap opt-in; database project dan collector
existing belum dimigrasikan/diganti. Detail deployment, batas kapasitas dan
recovery: `docs/ops/bandwidth-ingestion.md`.

## Pembaruan implementasi tahap keempat

Agregasi harian WIB dan API backend sudah tersedia. Tabel
`bandwidth_daily_usage` diperbarui dalam transaksi ingestion yang sama dengan
raw flow dan checkpoint. Counter MySQL DECIMAL mempertahankan total di atas
BIGINT; buffer bucket dan statement upsert dibatasi. API daftar klien memakai
keyset pagination, sementara daily usage/top subjects dibatasi rentang 31 hari.
Counter/timestamp API berupa string desimal, identitas unresolved terpisah dan
completeness selalu `unverified`.

Flow lintas hari dibagi dengan cumulative integer floors yang mengonservasi
jumlah byte dan menandai estimated bytes. Migrasi `20261015_0033` melakukan
backfill raw flow existing dengan allocation v1 yang dibekukan; worker wajib
dihentikan saat migrasi. Downgrade hanya membuang ringkasan turunan.

Validasi tahap keempat:

- Suite backend cepat: 378 lulus, 2 row-lock MySQL dilewati, 148 deselected.
- Suite inventory/ingestion/reporting pada MySQL 8.4 disposable: 40 lulus.
- Pemeriksaan MySQL final reporting/backfill: 11 lulus, termasuk total di atas
  BIGINT dan alokasi lintas 1.000 hari dengan buffer bounded.
- Verifikasi fokus final: 23 lulus, 1 row-lock MySQL dilewati. Tambahan validasi
  backfill midnight WIB lulus pada SQLite.
- Full Alembic upgrade dari kosong ke `0033`, schema check, downgrade `0032`,
  upgrade/check ulang dan single-head check lulus pada MySQL disposable.
- Lint/format 13 file, mypy 7 modul dan whitespace diff lulus.

Container/database uji sudah dibersihkan. Belum ada aktivasi atau migrasi pada
database project, perubahan router ataupun penggantian collector lama. UI,
rename klien, rekonsiliasi identitas tertunda, health/alert ingestion dan validasi
transfer nyata tetap menjadi pekerjaan berikutnya. Panduan kontrak dan batas
operasional: `docs/ops/bandwidth-reporting.md`.

## Pembaruan implementasi tahap kelima

UI tersedia sebagai tab **Bandwidth** pada halaman **Live Monitoring**. Pemilihan
router memakai tipe MikroTik dari API, bukan tebakan nama. Laporan harian WIB,
upload/download/total, alokasi estimasi, unresolved bytes, top pengguna dan
inventaris DHCP/ARP memakai komponen tabel, pagination dan kartu existing.
Klik nama klien memfilter histori harian; ranking tetap untuk seluruh router.

Query bandwidth terpisah dari metrik kesehatan dan dimuat hanya pada tab aktif.
Cache mencakup router/filter/pagination, pergantian router mereset klien, dan
request membawa AbortSignal. Inventaris/top dibatasi 10 baris per request;
tanggal diterapkan eksplisit dengan batas 31 hari. Rentang yang mencakup hari
ini dipoll 60 detik saat tab browser aktif. Byte tetap memakai BigInt sampai
formatter, dengan nilai utuh pada tooltip/label aksesibilitas.

Kelengkapan belum terverifikasi dan pembagian lintas hari ditampilkan sebagai
estimasi. Hari tanpa observasi tidak diisi nol; unresolved IP tidak diperlakukan
sebagai identitas perangkat. Loading/error/retry berdiri sendiri per bagian,
dan navigasi tab tetap tersedia ketika metrik kesehatan gagal.

Validasi tahap kelima:

- Seluruh suite frontend: 55 test pada 20 file lulus.
- Dua smoke test Playwright tersimpan di `frontend/e2e/bandwidth.spec.ts` lulus
  pada build production dengan seluruh API memakai fixture sintetis.
- Browser smoke tambahan: desktop 1.440 px, mobile 390 px, light/dark, URL filter
  nyata dan pergantian router lulus; tidak ada page error atau overflow dokumen.
- Screenshot desktop/mobile diperiksa, termasuk kontras tema, tabel horizontal
  dalam container dan keterbacaan angka ringkasan.
- ESLint, TypeScript, formatting modul baru dan production build lulus.
- Tidak ada perubahan schema atau aktivasi collector/router. Server frontend QA
  lokal sudah ditutup; container collector lama tidak disentuh.

Lima dari enam tahap utama selesai. Tahap berikutnya adalah aktivasi pipeline
dan validasi transfer nyata/arah/byte/keterlambatan sebelum pemakaian operasional.
Rename klien, rekonsiliasi identitas tertunda dan alert ingestion tetap tercatat
sebagai pengembangan terpisah. Panduan penggunaan: `docs/ops/bandwidth-reporting.md`.

## Persiapan tahap keenam — penerimaan live belum selesai

Preflight dibatasi ke Head Office. Router existing teridentifikasi sebagai ID 2,
bukan ID 1 dari policy generik. Konfigurasi Traffic Flow dibaca melalui API tanpa
perubahan router; Regional Office tidak dihubungi atau diaktifkan untuk bandwidth.
Sesudah pengguna menjelaskan sedang di luar kantor melalui VPN, pengujian jalur
IPFIX dan cutover collector ditunda.

DB existing semula tidak mempunyai `alembic_version`. Perbandingan terhadap model
sebelum bandwidth menghasilkan nol drift. Backup privat dibuat dan SHA-256-nya
dicatat; restore pada MySQL disposable, adopsi `0030`, upgrade `0033` dan schema
check lulus, dengan jumlah record 23 tabel existing tetap sama. Adopsi dan migrasi
kemudian diterapkan ke DB project dengan pemeriksaan yang sama. Tidak ada
penghapusan data existing atau rollback schema otomatis.

Tooling operasional baru:

- `backend.app.bandwidth.diagnostics`: status worker/counter, baseline transfer
  privat eksklusif, dan perbandingan byte/toleransi memakai integer exact.
- Scope observasi mengikuti router, IP perangkat, cursor committed dan digest
  policy. Flow router/IP/policy lain tidak tercampur. Record yang sudah mulai
  sebelum baseline ditandai agar operator dapat menilai kontaminasi window.
- `collector_health`: readiness manifest read-only tanpa dependency DB; tidak
  menginisialisasi atau mengganti binding spool. Compose menunggu collector sehat
  sebelum memulai worker, sehingga startup tidak berlomba dengan pembuatan manifest.
- Panduan aktivasi, rollback, penggunaan CLI, batas payload vs network bytes dan
  kendala VPN tersedia di `docs/ops/bandwidth-acceptance.md`.

Validasi persiapan tahap keenam:

- Suite backend cepat: 386 lulus, 2 row-lock MySQL dilewati, 148 deselected.
- Pemeriksaan fokus source final: 22 test validasi/spool lulus, termasuk isolasi
  router/policy, baseline tanpa overwrite, redaksi error, toleransi di atas BIGINT,
  window kosong dan readiness tanpa mutasi.
- Lint/format lima file, mypy empat modul, CLI help dan whitespace diff lulus.
- Konfigurasi Compose serta dependency readiness tervalidasi memakai environment
  dummy, tanpa memulai service atau menampilkan credential.

Docker daemon tidak tersedia pada pemeriksaan terakhir. Tes MySQL tambahan untuk
CLI baru dan cleanup `codex-bandwidth-adoption-test` belum dapat dikonfirmasi
ulang; backup dan laporan adopsi/migrasi tetap berada di folder `backup/` yang
diabaikan Git. Tidak ada penggantian collector lama atau aktivasi worker baru.
Status tetap lima dari enam tahap utama selesai; penerimaan live menunggu jalur
collector yang dapat diverifikasi dan transfer uji terkontrol.

## Hasil pemeriksaan awal project (historis)

| Area | Kondisi existing | Implikasi |
| --- | --- | --- |
| Backend | FastAPI, async SQLAlchemy, repository/service, Alembic | Tambahkan modul pada struktur existing. |
| Database | Compose memakai MySQL 8.4; driver PyMySQL/aiomysql | Gunakan MySQL existing; usulan PostgreSQL di chat sebelumnya bukan kebutuhan migrasi. |
| MikroTik | `backend/app/monitors/mikrotik/parts/impl.py` memakai librouteros, mendukung beberapa target | Reuse pengambilan DHCP/ARP dan identitas router; bukan membuat jalur REST API baru. |
| Identitas klien | DHCP/ARP dibaca untuk `dhcp_active_leases` dan `connected_clients` | Belum ada penyimpanan identitas klien atau histori assignment IP. |
| Inventaris existing | `devices` berisi target monitoring, dengan IP unik global | Klien LAN perlu tabel tersendiri agar discovery tidak otomatis memicu polling/alert target dan mendukung subnet sama di beberapa router. |
| Metrik | Counter interface/firewall/queue dan ringkasan klien | Belum ada pipeline IPFIX, per-client daily usage, atau endpoint bandwidth. |
| Frontend | Next.js, React Query, Plotly, komponen tabel dan formatter | Reuse komponen dan kontrak autentikasi existing. |
| GoFlow2 | `goflow2/mapping.yaml`, field NAT 225–228, protobuf di bawah formatter | Identik dengan `/Users/andimas/network-monitoring/goflow2/mapping.yaml`. |
| Runtime lokal | `mikrotik-netflow` berjalan pada UDP 2055 | Hanya status proses yang diverifikasi; penerimaan flow terbaru belum diperiksa pada audit ini. |
| Runtime aplikasi | Container project MySQL/backend/frontend/scheduler/notification-worker berhenti | Belum memverifikasi konektivitas DB atau aplikasi yang berjalan. PostgreSQL aktif yang terlihat bernama personal-finance, bukan database project ini. |

Ada perubahan lokal existing pada konfigurasi, notifikasi, UI, dan test. Audit ini tidak mengubah file tersebut, tidak menjalankan migrasi, dan tidak menyalakan/menghentikan container.

## Kontrak data yang perlu dipertahankan

Konteks pengujian dari percakapan: router L009 RouterOS 7.19.4, subnet `192.168.1.0/24`, WAN sfp1 ifIndex 10, LAN bridge-LAN ifIndex 13, collector MacBook `192.168.1.172:2055`. Nilai ini adalah konfigurasi saat eksperimen, belum diverifikasi ulang pada router.

- Upload eksperimen: LAN → WAN, perangkat dari `src_addr`.
- Download eksperimen: WAN → LAN, perangkat dari `post_nat_dst_addr` yang dinormalisasi dari hex.
- Interface dan subnet harus dapat dikonfigurasi per router. Jangan hardcode aturan satu router ke seluruh aplikasi.
- Arah WAN/LAN saja belum cukup untuk mendefinisikan internet: flow contoh menuju jaringan privat lewat WAN perlu kebijakan pengecualian. VPN, IPv6, dan layanan port forwarding perlu cakupan eksplisit.
- Simpan byte sebagai integer. Tanggal laporan menggunakan Asia/Jakarta dan mengikuti waktu flow, bukan sekadar waktu penerimaan.
- Flow yang melintasi tengah malam hanya menyediakan total byte dan interval waktu. Pembagian proporsional merupakan estimasi; tandai kebijakannya dan jangan menyebutnya pengukuran tepat per hari.
- Active timeout 30 menit pada eksperimen berarti hasil flow dapat terlambat; jangan menjanjikan grafik instan.
- DHCP bound tidak membuktikan online. Tampilkan sumber pengamatan dan last seen; hostname kosong memakai custom name, MAC, lalu IP.

## Rancangan integrasi

Alur: MikroTik → GoFlow2 → spool persisten → worker flow → MySQL → FastAPI → halaman bandwidth.

1. **Normalisasi dan klasifikasi:** modul terpisah untuk validasi IPFIX, decode NAT hex, timestamp, subnet dan interface per router. Record invalid/tidak terklasifikasi punya counter alasan dan tidak diam-diam dihitung nol.
2. **Inventaris klien:** tabel `bandwidth_clients` dengan router scope, MAC opsional, hostname asli, nama manual dan last seen; `bandwidth_client_ip_history` menyimpan interval pengamatan assignment. Gunakan FK ke router dalam tabel `devices`. Polling DHCP/ARP hanya memberi interval observasi, bukan bukti waktu assignment tepat; ambiguity dan perangkat statis tetap harus ditangani.
3. **Penerimaan persisten:** output GoFlow2 menuju volume spool, bukan membaca ulang `docker logs`. Worker memproses segmen lengkap dan menyimpan checkpoint secara transaksional bersama hasil pemrosesan. Rotasi, retensi, batas disk dan backpressure harus ditentukan.
4. **Idempotensi:** identitas record dari segmen/offset yang stabil mencegah replay spool dihitung ulang. Ini tidak otomatis mendeteksi duplikasi ekspor UDP. Jangan memakai hash IP/port/byte saja karena flow valid bisa identik. Mapping saat ini juga belum mempertahankan identitas exporter/sequence; siapkan routing sumber per collector atau metadata exporter untuk multi-router sebelum ingest beberapa router.
5. **Penyimpanan:** tabel flow/interval terpisah dari metrik health existing, ringkasan harian yang dapat dibangun ulang, dan status worker/checkpoint/gap data. Daily usage menyertakan indikator kelengkapan dan data yang belum terpetakan.
6. **API:** daftar klien per router, rename dengan izin write dan audit, daily usage/top users, histori dengan rentang terbatas, health collector. Terapkan autentikasi existing dan pagination. Namespace usulan `/bandwidth`, belum kontrak final.
7. **UI:** halaman penggunaan perangkat dengan filter router/tanggal, upload/download/total, histori, nama manual, last seen, waktu pembaruan dan status kelengkapan. Gunakan komponen existing. Jangan mencampur inventaris klien otomatis dengan target polling existing.

## Urutan implementasi dan validasi

1. Bangun normalizer/classifier dan test fixture offline: NAT hex, upload/download, subnet/WAN yang dikecualikan, timestamp invalid, flow terlambat, batas hari dan record tidak didukung.
2. Tambah model dan migrasi MySQL dengan upgrade/downgrade, mengikuti gate repository. Integrasikan sinkronisasi identitas tanpa memanggil RouterOS dua kali setiap siklus.
3. Tambah spool/worker dan test crash/replay/checkpoint serta assignment IP yang berubah. Pastikan kegagalan DB tidak menghilangkan segmen belum committed.
4. Tambah endpoint dan UI dengan test autentikasi, isolasi router, rename dan pagination.
5. Jalankan migration gate dan test integrasi MySQL pada database uji. Nyalakan layanan project untuk smoke test setelah konfigurasi siap; hindari menyentuh layanan Docker lain.
6. Uji satu perangkat dengan transfer berukuran diketahui; bandingkan byte, arah, overhead, timeout ekspor dan kelengkapan. Ukur beban router. Tentukan hasil untuk VPN/IPv6/port forwarding dan periode collector offline sebelum menyebut laporan harian tervalidasi.

Audit ini tidak memerlukan test aplikasi karena belum mengubah kode executable. Rancangan di atas belum membuktikan akurasi accounting atau kelengkapan ekspor router.
