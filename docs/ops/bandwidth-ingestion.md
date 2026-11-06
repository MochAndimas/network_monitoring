# Ingestion IPFIX

Konfigurasi utama: [panduan operasi](bandwidth.md). Runtime collector/worker
tersedia bersama agregasi harian, API dan UI Live Monitoring. Rekonsiliasi
identitas terlambat dilakukan inventory worker secara transaksional; lihat
[reporting](bandwidth-reporting.md). Aktivasi/pengukuran mengikuti
[panduan penerimaan](bandwidth-acceptance.md).

## Alur dan kontrak replay

MikroTik → GoFlow2 → stdout pipe → spool lokal → worker → MySQL.

Supervisor collector menjalankan binary GoFlow2 secara langsung, tanpa shell atau
pembacaan ulang Docker logs. GoFlow2 memang mendukung JSON stdout dan custom
mapping; lihat [README resmi](https://github.com/netsampler/goflow2/blob/main/README.md).
Binary dari image resmi dipakai pada runtime Python Alpine yang kompatibel dengan
runtime image asal. Image default Dockerfile dipin ke digest yang diuji; Compose
meminta operator memilih `GOFLOW2_IMAGE` secara eksplisit.

Spool satu router mempunyai manifest `.stream.json` dengan UUID stream dan ID
router yang persisten. Writer memakai file lock POSIX eksklusif, mengelompokkan
record utuh dari chunk stdout maksimum 64 KiB untuk satu fsync per batch, lalu
melakukan rotasi maksimum 4 MiB atau setiap satu detik.
Nama `.ready` berisi UUID segmen dan SHA-256. Rename dan perubahan direktori juga
di-fsync. Worker hanya membaca file regular sealed, memverifikasi ukurannya dan
checksum sebelum memproses byte. File `.open` akibat crash dipublikasikan saat
collector restart; ekor record yang terpotong dicatat sebagai `incomplete_record`.

Progress, flow valid dan counter penolakan di-commit dalam satu transaksi. Kunci
unik `(stream_id, segment_id, record_offset)` dan checkpoint byte mencegah replay
posisi yang sama memasukkan flow dua kali. File baru dihapus setelah seluruh
segmen berhasil committed. Crash antara commit dan penghapusan aman untuk replay.

Jaminan ini berlaku untuk record yang telah masuk spool, **bukan exactly-once UDP**.
Duplikasi datagram dari exporter belum dideteksi; dua record identik di offset
berbeda tetap dihitung sebagai dua observasi. Kehilangan saat collector offline,
template belum tersedia, pipe/backpressure, overload atau paket UDP hilang tidak
dapat dipulihkan oleh checkpoint. Counter seq dari GoFlow2 dipertahankan pada
output mapping, tetapi belum dipakai untuk menyimpulkan kelengkapan.

## Penyimpanan dan kualitas data

- `bandwidth_flow_streams`: binding router/policy, heartbeat dan status worker.
- `bandwidth_flow_segments`: ukuran/checksum, checkpoint byte, jumlah accepted/
  rejected dan tanda completion. Retain checkpoint saat raw flow dipensiunkan
  nanti agar restore spool tidak menyebabkan accounting ulang.
- `bandwidth_flow_rejections`: counter alasan stabil per stream. Raw record invalid
  tidak disimpan di DB atau dicetak oleh worker.
- `bandwidth_flows`: arah, IP perangkat/remote, alamat sebelum/sesudah NAT,
  interface, byte/paket dan timestamp nanodetik asli. Integer tidak diubah menjadi
  float. Identitas `client_id` boleh NULL jika histori tidak menutupi seluruh flow.

Lookup identitas memakai query per chunk IP dan dibatasi jumlah histori, bukan
satu query per flow. Insert flow memakai batch SQL. Transfer yang belum punya
identitas tetap tersimpan berdasarkan IP/router untuk reconciliation kemudian.
Raw flow ini belum menjadi angka harian tervalidasi; jangan membagi ke tanggal
receipt atau menyebut transfer lintas tengah malam sudah dialokasikan tepat.

Tiap worker/volume terikat **satu router dan satu policy exporter**. Policy JSON wajib
mencantumkan ID router existing, exporter, interface, subnet dan pengecualian
remote. `sampler_address` harus sama dengan exporter atau salah satu `exporter_aliases`
yang sudah diverifikasi. Alias opsional hanya untuk alamat transport router yang
sama (misalnya NAT Docker LAN/VPN), maksimal delapan IPv4 unik. Perubahan alias
mengubah digest policy dan memerlukan stream baru; bukan wildcard sumber.
Mapping project kini menyertakan field ini beserta `sequence_num`. Jangan langsung
menyalin nilai exporter contoh tanpa mencocokkan output decoder dan sumber UDP
router. Konfigurasi lama tanpa field exporter akan menghasilkan penolakan.

IP sumber UDP yang dapat dipalsukan bukan autentikasi. Batasi akses listener ke
exporter pada jaringan/firewall deployment; jangan gabungkan dua router ke volume
atau listener contoh ini. Untuk banyak router, gunakan pasangan collector/worker
dan volume berbeda (port berbeda bila pada host sama). Row lock router di MySQL
menserialisasi write per router, termasuk terhadap sinkronisasi inventaris.

Policy memiliki digest versi. Perubahan router/exporter/interface/subnet atau
filter pada stream yang sudah terdaftar ditolak. Drain stream lama, simpan
konfigurasinya, lalu buat volume/manifest baru untuk kebijakan baru. Jangan
menghapus atau mengganti UUID manifest pada backlog existing. Manifest hilang
dengan backlog tertinggal membuat collector berhenti, bukan memberi ID baru.

## Kapasitas, kegagalan dan health

Default collector membatasi spool ke 256 MiB dan 256 file. Tidak ada eviction
record unread: jika penuh, collector berhenti dan proses decoder diterminasi.
Segmen yang sudah ditulis tetap dipertahankan. Restart dapat melanjutkan setelah
worker mengurangi backlog, tetapi traffic UDP selama hambatan ini dapat hilang.
Fsync setiap batch append mengutamakan durabilitas; ukur disk/throughput pada traffic
kantor sebelum penggunaan terus-menerus.

Worker memproses default 500 record per transaksi, dengan batas segmen 64 MiB.
Database outage melakukan rollback dan retry dengan backoff maksimum 30 detik.
Segmen rusak, identitas segmen berubah, atau segmen yang sudah punya checkpoint
parsial menghilang membuat worker berhenti. File yang hilang sebelum pertama
kali terdaftar di database belum bisa dideteksi. Jangan menghapus manual backlog.

`python -m backend.app.bandwidth.worker health` memeriksa heartbeat maksimum 45
detik, status running/idle dan binding policy. Ini health proses ingestion, bukan
bukti kelengkapan traffic atau status collector UDP. Periksa juga container
collector/restart count, ukuran backlog dan rejection counters. Belum ada alert
otomatis untuk status ini pada System Health. Status berhenti teratur dicatat
sebagai error code `worker_stopped`; crash keras akan membuat heartbeat stale.

Runtime spool mendukung local filesystem POSIX pada Linux/macOS. Gunakan Docker
pada Windows. Shared network filesystem belum menjadi deployment yang divalidasi.
Belum ada retention raw flow otomatis pada DB; tentukan retensi sebelum volume
traffic besar dipakai terus-menerus. Segmen filesystem yang sudah committed
dihapus otomatis, checkpoint DB tetap disimpan.

## Deployment

1. Backup DB project, lalu upgrade schema melalui `20261015_0033`. Hentikan worker
   ingestion selama migrasi/backfill sesuai panduan reporting. Aktifkan satu
   collector inventory agar flow dapat dipetakan ke klien.
2. Buat salinan `goflow2/flow-policy.example.json`, sesuaikan dengan router/ifIndex
   dan exporter yang diverifikasi. Tanggal laporan memakai Asia/Jakarta;
   timestamp flow tetap UTC epoch nanodetik.
3. Set variabel Compose: `GOFLOW2_IMAGE`, `BANDWIDTH_ROUTER_ID`, dan
   `BANDWIDTH_FLOW_POLICY_PATH` (path absolut ke policy hasil review).
4. Review `docker-compose.yml`. Listener default hanya bind
   localhost; untuk router fisik, set `BANDWIDTH_LISTEN_ADDRESS` ke alamat LAN
   collector yang telah disetujui dan batasi jalur UDP dari exporter.
5. Koordinasikan penghentian collector lama sebelum listener pengganti memakai
   port yang sama. Perintah persiapan/build, tanpa menjalankan service:

   ```sh
   docker compose config --quiet
   docker compose build flow-collector flow-worker
   ```

6. Setelah konfigurasi/migrasi siap, `docker compose up -d --build` menjalankan
   aplikasi beserta collector/worker/inventory kedua site. Untuk operasi khusus
   HO, pilih nama service secara eksplisit. Collector dan worker masing-masing
   site memakai volume bersama dengan UID 10001.
   Jangan melakukan `down -v` pada volume yang berisi spool/checkpoint.
7. Verifikasi state worker, received/rejected counters dan byte dari transfer uji
   mengikuti panduan aktivasi. Daily report dan UI sudah tersedia, tetapi
   completeness tetap belum terverifikasi.

Di luar Docker, entry point tersedia:

```sh
python -m backend.app.bandwidth.collector --router-id ROUTER_ID --binary /path/to/goflow2 --mapping /path/to/mapping.yaml --directory /path/to/spool
# Environment: BANDWIDTH_INGESTION_ENABLED=true, BANDWIDTH_FLOW_POLICY_FILE,
# BANDWIDTH_SPOOL_DIRECTORY, DATABASE_URL (serta settings environment existing).
python -m backend.app.bandwidth.worker once
python -m backend.app.bandwidth.worker run
python -m backend.app.bandwidth.worker health
```

SIGTERM/SIGINT collector menghentikan decoder lalu drain stdout dan seal segmen
terakhir. Worker menyelesaikan transaksi aktif sebelum keluar. Batas grace
container tetap menjadi batas operasi; SIGKILL bergantung pada recovery/rollback.

Downgrade ke `0031` hanya diizinkan jika empat tabel ingestion kosong. Riwayat
flow/replay tidak dihapus otomatis oleh migrasi. Ekspor dan pensiunkan secara
eksplisit jika schema memang harus dibatalkan.
