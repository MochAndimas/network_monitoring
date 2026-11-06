# Operasi backend bandwidth

Panduan utama konfigurasi dan deployment. Catatan eksperimen LAN/VPN tetap di
[acceptance](bandwidth-acceptance.md), bukan nilai default instalasi baru.

## Struktur dan tanggung jawab

| Lokasi | Tanggung jawab |
| --- | --- |
| `backend/app/bandwidth/` | Domain flow murni, spool, entrypoint collector/worker/diagnostics |
| `backend/app/services/bandwidth_*` | Transaksi ingestion, inventory, rekonsiliasi, query, validasi |
| `backend/app/repositories/bandwidth_*` | Query dan upsert database; commit milik caller |
| `backend/app/models/bandwidth*`, `alembic/versions/20261015_003*` | Schema dan migrasi |
| `goflow2/mapping.yaml` | Kontrak decoder IPFIX dan field NAT yang dipin |
| `goflow2/flow-policy.example.json` | Template policy tanpa nilai instalasi aktif |
| `goflow2/flow-policy.local.json` | Policy instalasi lokal, diabaikan Git |
| `docker-compose.yml` | Deployment utama, termasuk HO dan RO |

Seluruh layanan, termasuk bandwidth HO/RO, berada di `docker-compose.yml` dan
aktif secara default. Jalankan `docker compose up -d --build`. Hanya migrasi
memakai profile `ops`. File `docker-compose.bandwidth.yml` kini shim kosong
untuk kompatibilitas perintah lama; symlink `docker-compose.flow-ingest.example.yml`
tetap menuju shim tersebut. Perintah baru cukup memakai Compose utama.

## Sumber konfigurasi

Settings backend dibaca lewat `core/config.py`: env proses mengalahkan `.env`.
Collector dan health collector sengaja hanya memakai stdlib/environment agar image
decoder tidak membawa dependency API/database. Argumen CLI eksplisit mengalahkan
default settings inventory.

| Pengaturan | Tempat / makna |
| --- | --- |
| `BANDWIDTH_ROUTER_ID` | Compose; identitas manifest, harus sama dengan policy |
| `BANDWIDTH_LISTEN_ADDRESS`, `BANDWIDTH_LISTEN_PORT` | Compose; bind host, default loopback UDP 2055 |
| `BANDWIDTH_FLOW_POLICY_PATH` | Compose; path **host** menuju JSON yang ditinjau |
| `BANDWIDTH_FLOW_POLICY_FILE` | Runtime backend; path policy **di dalam proses**, `/etc/bandwidth/policy.json` pada Compose |
| `BANDWIDTH_FLOW_SPOOL_VOLUME` | Compose; named volume persisten untuk satu stream/policy |
| `GOFLOW2_IMAGE` | Compose/build; digest decoder yang diuji |
| `BANDWIDTH_INGESTION_ENABLED` | Runtime worker; diaktifkan pada service ingestion Compose |
| `BANDWIDTH_SPOOL_DIRECTORY` | Runtime; direktori spool, sama untuk writer/worker |
| `BANDWIDTH_INGESTION_BATCH_SIZE`, `BANDWIDTH_INGESTION_POLL_SECONDS` | Runtime; batas batch dan polling tervalidasi |
| `BANDWIDTH_INVENTORY_ENABLED` | Runtime; opt-in observasi DHCP/ARP |
| `BANDWIDTH_INVENTORY_TARGET_NAME` | Runtime inventory mandiri; satu key dari `MIKROTIK_TARGETS` |
| `BANDWIDTH_INVENTORY_API_HOST`, `BANDWIDTH_INVENTORY_API_PORT` | Endpoint API utama; nilai kosong memakai host/port target |
| `BANDWIDTH_INVENTORY_API_FALLBACK_HOST`, `BANDWIDTH_INVENTORY_API_FALLBACK_PORT` | Endpoint kedua router yang sama, opsional |
| `BANDWIDTH_INVENTORY_ROUTER_IDENTITY` | Nama `/system identity` yang harus cocok; wajib untuk fallback |
| `BANDWIDTH_INVENTORY_POLL_SECONDS`, `BANDWIDTH_INVENTORY_MAX_GAP_SECONDS` | Runtime; polling harus paling lama separuh batas gap |

Credential berasal dari konfigurasi database/auth/`MIKROTIK_TARGETS` existing.
Jangan menaruh credential di policy. `router_id`, exporter, subnet dan interface
hanya berada pada satu policy aktif; digestnya immutable setelah stream terdaftar.
Perubahan alamat listener/API saja tidak perlu mengganti stream. Jika exporter
yang benar-benar terlihat decoder berubah, tinjau policy dan gunakan volume stream
baru. Histori DB dan volume lama tetap disimpan.

## Menjalankan dan memeriksa

1. Migrasikan schema sampai `20261015_0033`, siapkan backup, dan tinjau policy.
2. Salin template policy ke `goflow2/flow-policy.local.json`; isi variabel Compose
   pada `.env`. File ini terbaca user container; `.env` tetap privat.
3. Jalankan `make bandwidth-config` (tidak mencetak secret).
4. Build/start hanya layanan yang diperlukan:

```sh
docker compose build flow-collector flow-worker flow-inventory
docker compose up -d flow-collector flow-worker flow-inventory
make bandwidth-status
make bandwidth-logs
```

Inventory mandiri hanya diperlukan bila scheduler existing belum mengumpulkan
inventory router yang sama. Jangan menyalakan dua poller untuk router itu.
Perintah di atas tidak menjalankan scheduler/notification worker. Tidak memulai
inventory mandiri? Hilangkan `flow-inventory` dari build/start.

Status `healthy` bukan bukti UDP masuk. Pastikan receipt terbaru, accepted flow
bertambah, pending nol, policy cocok, dan report API terautentikasi berisi data.
Counter diagnostics mencakup stream historis; stream berhenti memang tidak hidup.
Heartbeat masa depan ditolak sama seperti heartbeat kedaluwarsa.

Untuk masalah publish UDP, ikuti pemulihan scoped pada acceptance: drain, hapus
hanya container collector berhenti, buat ulang dengan **volume yang sama**, lalu
uji IPFIX nyata. Jangan menghapus volume atau merestart semua project secara otomatis.

## Panduan khusus

- [Ingestion dan recovery spool](bandwidth-ingestion.md)
- [Inventaris dan coverage identitas](bandwidth-inventory.md)
- [API, alokasi harian, rekonsiliasi](bandwidth-reporting.md)
- [Cutover, pengukuran transfer, rollback](bandwidth-acceptance.md)

Raw flow/checkpoint dan histori identitas belum memiliki kebijakan retention
otomatis. Pantau pertumbuhan DB; jangan menghapus raw flow tanpa merancang dampak
terhadap rekonsiliasi, pengukuran transfer, dan audit checkpoint.

## LAN/VPN otomatis untuk satu router

Collector dapat dipublish pada `BANDWIDTH_LISTEN_ADDRESS=0.0.0.0` agar IP LAN dan
IP VPN Mac yang berubah tetap memakai UDP 2055 tanpa recreate container. Ini
membuka listener pada seluruh interface IPv4 host; gunakan hanya jaringan yang
dipercaya dan batasi sumber UDP 2055 lewat firewall host/router bila diperlukan.
Listener tidak mengubah target Traffic Flow MikroTik dan tidak menyalakan VPN.

Inventory mendukung endpoint utama dan fallback untuk **router yang sama**:

```dotenv
BANDWIDTH_LISTEN_ADDRESS=0.0.0.0
BANDWIDTH_LISTEN_PORT=2055
BANDWIDTH_INVENTORY_API_HOST=10.10.10.1
BANDWIDTH_INVENTORY_API_PORT=8728
BANDWIDTH_INVENTORY_API_FALLBACK_HOST=192.168.1.1
BANDWIDTH_INVENTORY_API_FALLBACK_PORT=8728
BANDWIDTH_INVENTORY_ROUTER_IDENTITY=Rtr.UTAMA SSKB
BANDWIDTH_INVENTORY_POLL_SECONDS=30
```

Setiap poll mencoba API VPN terlebih dahulu. Jika koneksi, autentikasi, identity,
atau pembacaan DHCP/ARP gagal, worker mencoba LAN. Poll berikutnya tetap mencoba
VPN dulu sehingga reconnect pulih otomatis. Pemilihan berdasarkan API yang bisa
dibaca lengkap, bukan hanya status tombol aplikasi VPN. Router inventory harus
cocok dengan binding DB dan `/system identity` yang dikonfigurasi; router rumah
yang kebetulan memakai `192.168.1.1` tidak boleh dipetakan sebagai Head Office.
Jika keduanya gagal, snapshot lama tidak diperbarui dan health menjadi stale.
Port API pada contoh adalah konfigurasi instalasi ini, bukan default OpenVPN;
Traffic Flow tetap UDP 2055. Port override kosong memakai port target existing.
Identity wajib diisi ketika fallback digunakan. CLI `--api-port`, `--fallback-port`, `--api-host`,
`--fallback-host`, dan `--router-identity` mengalahkan settings.

Docker Desktop dapat mengganti source exporter menjadi gateway NAT. Policy
mendukung field opsional `exporter_aliases`: array maksimal delapan IPv4 unik
yang telah diverifikasi, tanpa CIDR/wildcard. Contoh lokal: exporter utama
`192.168.65.1`, alias `172.19.0.1`. Source lain tetap ditolak. Alias mengubah
digest policy sehingga aktivasi pertama memerlukan **volume stream baru**;
volume lama dan histori DB dipertahankan. Setelah aktivasi ini, perpindahan
LAN/VPN dengan alias yang sama tidak memerlukan perubahan file atau volume.
Policy tanpa alias tetap memiliki digest lama. Gateway NAT bukan bukti identitas
router; jangan kirim flow router lain ke listener khusus Head Office ini.

Yang perlu diubah di MikroTik saat berpindah lokasi hanya destination target
Traffic Flow: IP VPN Mac saat VPN aktif (baca ulang karena alokasinya dinamis),
atau IP LAN Mac saat di kantor. Port tetap 2055. Akses API router juga harus
mengizinkan sumber koneksi LAN/VPN yang berlaku; perubahan alamat pool VPN dapat
memerlukan pembaruan allowlist MikroTik. Project tidak mengubah firewall router.

Periksa `make bandwidth-status` dan `make bandwidth-logs`. Log
`Inventory connection selected` menunjukkan endpoint yang berhasil. Uji
perpindahan nyata dengan mengamati accepted flow bertambah di kedua mode;
health collector saja tidak membuktikan penerimaan UDP. Jika Docker mengganti
subnet/gateway di luar alias yang ditinjau, source ditolak sampai policy ditinjau
ulang dengan stream baru.

## Menjalankan Head Office dan Regional Office bersamaan

Compose utama menyediakan template collector, worker dan inventory melalui
YAML anchors. HO memakai `flow-collector`, `flow-worker`, `flow-inventory`.
RO memakai suffix `-ro`. Keduanya dijalankan default tanpa profile bandwidth.
Setiap collector mempunyai port host dan volume spool sendiri. Runtime domain,
API dan UI tetap sama; semua query terikat `router_id`.

| Binding instalasi lokal | Head Office | Regional Office |
| --- | --- | --- |
| Router ID DB | 2 | 41 |
| Port host UDP | 2055 | 2056 |
| LAN | 192.168.1.0/24 | 192.168.88.0/24 |
| ifIndex LAN / WAN | 13 / 10 | 11 / 2 |
| API VPN | 10.10.10.1:8728 | 10.20.20.1:8728 |
| Identity | Rtr.UTAMA SSKB | Mikrotik SSKB RO |

Nilai ID harus diperiksa dari DB setiap instalasi, bukan disalin dari tabel ini.
Port container RO tetap 2055; mapping host 2056 memisahkan UDP kedua router,
termasuk ketika Docker NAT menampilkan IP exporter yang sama. Jangan menaruh
keduanya dalam satu listener/volume dan jangan memakai subnet client untuk
menebak router sumber.

Konfigurasi RO tersendiri pada `.env`:

```dotenv
BANDWIDTH_RO_ROUTER_ID=41
BANDWIDTH_RO_LISTEN_ADDRESS=0.0.0.0
BANDWIDTH_RO_LISTEN_PORT=2056
BANDWIDTH_RO_FLOW_POLICY_PATH=/absolute/path/goflow2/flow-policy.regional-office.local.json
BANDWIDTH_RO_FLOW_SPOOL_VOLUME=network_monitoring_bandwidth_ro_v1
BANDWIDTH_RO_INVENTORY_TARGET_NAME=regional-office
BANDWIDTH_RO_INVENTORY_API_HOST=10.20.20.1
BANDWIDTH_RO_INVENTORY_API_PORT=8728
BANDWIDTH_RO_INVENTORY_API_FALLBACK_HOST=
BANDWIDTH_RO_INVENTORY_API_FALLBACK_PORT=
BANDWIDTH_RO_INVENTORY_ROUTER_IDENTITY=Mikrotik SSKB RO
BANDWIDTH_RO_INVENTORY_POLL_SECONDS=30
```

RO tidak mewarisi endpoint fallback LAN HO. Tanpa jalur RO yang terjangkau,
inventory RO mempertahankan snapshot terakhir dan menjadi stale; tidak beralih
ke MikroTik HO. Credential `regional-office` tetap berasal dari `MIKROTIK_TARGETS`,
tidak disalin ke policy.

```sh
make bandwidth-config BANDWIDTH_SITE=ro
make bandwidth-up BANDWIDTH_SITE=ro
make bandwidth-status BANDWIDTH_SITE=ro
make bandwidth-logs BANDWIDTH_SITE=ro
```

Tanpa `BANDWIDTH_SITE`, perintah Make tetap memilih HO. `docker compose up -d --build`
menjalankan aplikasi utama, scheduler, notification worker, serta bandwidth HO/RO.
Untuk operasi scoped, berikan nama service secara eksplisit. Router ID dan path
policy HO/RO wajib diisi; Compose menolak konfigurasi kosong sebelum startup.
Pada instalasi baru, migrasikan schema dan siapkan policy kedua router dahulu.

Aktivasi router RO dilakukan sesudah readiness collector berhasil. Pastikan IP
VPN Mac masih `10.20.20.10`, ping dari RO berhasil, API mengizinkan IP client itu,
identity cocok, dan ifIndex dikonfirmasi melalui `/interface print oid`.
Traffic Flow menggunakan `bridge-LAN`, version `ipfix`, target
`10.20.20.10:2056`, enabled yes. Jangan mengubah FastTrack/offload/queues sebagai
bagian dari aktivasi. Eksklusi jaringan privat tetap berlaku; completeness
belum terverifikasi sampai transfer terkontrol diuji.

Pada aktivasi lokal RO, exporter yang diamati GoFlow2 adalah `172.19.0.1`.
Policy lokal mencakup gateway Docker yang ditinjau dan terikat ke stream RO
sendiri. Setelah flow aktif, periksa pertambahan accepted, receipt terbaru,
backlog dan rejection exporter. Pemilihan "Mikrotik - Regional Office" pada
Live Monitoring → Bandwidth memakai router ID 41; tidak perlu halaman terpisah.

Rollback RO: nonaktifkan Traffic Flow RO terlebih dahulu, hentikan collector RO,
biarkan worker RO menghabiskan spool, lalu hentikan worker/inventory RO. Volume,
policy dan histori DB tetap disimpan. Konfigurasi router sebelum aktivasi lokal
tersimpan privat di `backup/bandwidth-activation/ro-before-activation.json`.
