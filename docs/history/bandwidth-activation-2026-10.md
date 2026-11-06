> Arsip sesi 15–20 Oktober 2026. Untuk konfigurasi saat ini gunakan
> [panduan operasi](../ops/bandwidth.md). Nilai IP/volume di sini adalah catatan instalasi tersebut.

# Aktivasi dan penerimaan bandwidth Head Office

## Konfigurasi aktif LAN — 20 Oktober 2026

Mac kembali terhubung langsung melalui `en0`, IP `192.168.1.172/24`; ping dua arah
dengan router `192.168.1.1` berhasil tanpa loss. VPN tidak diperlukan untuk jalur
collector/inventory ini. Target RouterOS yang diverifikasi adalah Head Office
`Rtr.UTAMA SSKB`, device ID 2, format IPFIX, Traffic Flow aktif.

- Target IPFIX router: **192.168.1.172:2055/UDP**.
- `.env`: `BANDWIDTH_LISTEN_ADDRESS=192.168.1.172`, `BANDWIDTH_LISTEN_PORT=2055`,
  `BANDWIDTH_INVENTORY_API_HOST=192.168.1.1`.
- Policy lokal: `goflow2/flow-policy.head-office-lan.local.json`, exporter yang
  terlihat di decoder **192.168.65.1**. Alamat perantara Docker ini bukan bukti
  identitas asal router; jangan mengganti policy berdasarkan asumsi IP LAN saja.
- Spool aktif: `network_monitoring_bandwidth_ho_lan_v1`; policy dan volume VPN
  sebelumnya tetap disimpan. Tidak ada penghapusan histori atau migrasi schema.

Riwayat workaround sementara 2056 (sudah dicabut): setelah container dibuat ulang pada LAN, publish UDP 2055
terlihat ada tetapi tidak meneruskan probe host ke decoder. Probe pada IP LAN
yang sama dengan publish UDP 2056 berhasil. Target router dan publish collector
kemudian disamakan ke 2056; port decoder **di dalam container tetap 2055**.
Restart hanya collector tidak memulihkan mapping 2055. Tidak membuka bind ke
seluruh interface dan tidak merestart Docker Desktop/layanan lain. Container
probe sementara sudah dihapus. Jika port luar diubah lagi, ubah kedua sisi dan
verifikasi penerimaan, jangan hanya mengandalkan `healthy`.

### Pemulihan port 2055, sesi lanjutan 20 Oktober

Atas permintaan pengguna, port standar 2055 dipulihkan. Sebelum perbaikan, `lsof`
menunjukkan hanya listener Docker 2056. Mapping baru 2055 pada container probe
terpisah berhasil menerima datagram IPFIX. Kemudian collector 2056 dihentikan,
worker dibiarkan drain (pending nol), dan hanya container collector berhenti
dihapus tanpa menghapus named volume. Container probe juga dihapus. `lsof`
mengonfirmasi kedua port telah dilepas sebelum membuat mapping collector bersih.

`.env` dikembalikan ke port 2055, collector dibuat ulang dari image yang sama
dengan spool/manifest LAN yang sama, dan target RouterOS dikembalikan ke 2055.
Listener host terverifikasi hanya `192.168.1.172:2055`; tidak ada listener 2056.
GoFlow2 mencatat 2.960 DataFlowSet record dan 30 template setelah startup;
accepted flow naik dari 197.462 sebelum cutover ke 200.135, receipt terbaru dan
pending nol. Ini membuktikan pemulihan fungsional pada 2055, bukan diagnosis pasti
bug internal Docker Desktop atau jaminan masalah tidak akan berulang.

Prosedur pemulihan scoped bila gejala berulang: periksa mapping dan listener,
hentikan hanya collector, drain/check spool, hapus hanya container collector
berhenti (`flow_compose rm -f flow-collector`), pastikan port dilepas, lalu buat
ulang (`flow_compose up -d --no-build --no-deps flow-collector`). Pertahankan
volume/checkpoint dan target 2055. Verifikasi template, flow committed, receipt
terbaru dan backlog; jangan memakai `down -v`, reset database, atau restart seluruh
Docker sebagai langkah awal. Tidak ada layanan lain yang direstart pada pemulihan.

Inventory LAN membaca 75 perangkat pada preflight. Setelah pergantian policy/port,
accepted flow bertambah dari 179.906 menjadi 180.184, receipt terbaru sesuai waktu
aktivasi, pending segment nol, dan counter `unexpected_exporter` tidak bertambah
pada stream LAN. Counter router mencakup penolakan historis saat masih memakai
policy lama. Jeda cutover/record yang ditolak bukan data lengkap dan tidak cocok
untuk uji transfer terukur. Penerimaan operasional dan uji ukuran transfer tetap
belum dinyatakan selesai. Bagian OpenVPN di bawah adalah catatan historis.

Status 19 Oktober 2026: **cutover Head Office melalui OpenVPN sudah dilakukan**;
flow nyata tersimpan dan endpoint laporan terverifikasi. Uji transfer dengan
ukuran diketahui masih belum dilakukan. Regional Office tidak ikut diaktifkan.

## Hasil aktivasi OpenVPN 19 Oktober 2026

Pengguna mengubah tujuan IPFIX menjadi `10.10.10.42:2055` dan mengaktifkan Traffic
Flow. Mac menerima paket pada `utun4` dari `10.10.10.1:2055`; ping dua arah dan
capture UDP berhasil. Interface pada record live mengonfirmasi upload 13→10 dan
download 10→13. LAN `192.168.1.0/24` tetap berbeda dari subnet VPN.

GoFlow2 manual melihat sumber `192.168.65.1`, tetapi collector Compose melihat
gateway network `network_monitoring_default`, yaitu `172.19.0.1`. Policy percobaan
pertama menolak 3.068 record dengan `unexpected_exporter`; tidak ada record itu
yang diterima atau di-replay. Policy dikoreksi setelah gateway dan sampler spool
diverifikasi. Policy dan manifest stream immutable, sehingga dibuat volume baru
`network_monitoring_bandwidth_ho_vpn_v2`; volume awal disimpan untuk audit.
Alamat gateway Docker bukan identitas/autentikasi router dan bisa berubah jika
network dibuat ulang. Pembatasan sumber asli harus dilakukan sebelum NAT Docker
untuk deployment operasional; jangan menganggap allowlist gateway membuktikan
asal router. Listener tes hanya bind ke IP VPN Mac, bukan seluruh interface.

Konfigurasi lokal berada dalam `.env` dan policy
`goflow2/flow-policy.head-office-vpn.local.json`, keduanya diabaikan Git. Jangan
menyalin nilai ini ke instalasi lain. Nilai `BANDWIDTH_FLOW_SPOOL_VOLUME` menentukan
volume aktif sehingga perintah dua file berikut memakai stream yang sama:

```sh
flow_compose() {
  docker compose -f docker-compose.yml -f docker-compose.bandwidth.yml --profile bandwidth "$@"
}
flow_compose ps
flow_compose exec -T flow-worker python -m backend.app.bandwidth.diagnostics status
```

Collector lama `mikrotik-netflow` berhenti dan tetap tersedia untuk rollback.
MySQL, collector, ingestion worker, API dan frontend aktif. Endpoint daily/top
terautentikasi mengembalikan HTTP 200 dengan data nyata. Pemeriksaan konsistensi
menemukan 4.169 flow upload (31.388.778 byte) dan 3.987 flow download (426.604.301
byte), sama persis dengan total agregasi harian pada checkpoint pemeriksaan.
Angka ini terus berubah dan bukan hasil transfer terukur. Counter CLI mencakup
stream awal yang gagal, bukan hanya policy aktif; periksa stream/policy untuk
membedakan penolakan historis dari masalah baru.

API awalnya menutup koneksi; setelah pengguna membuka akses, snapshot Head Office
mencatat 105 perangkat tanpa konflik/invalid row. Worker opsional `flow-inventory`
memilih hanya target `head-office` dan router ID dari policy. Alamat API eksplisit
`10.10.10.1` memakai credential target existing; kecocokan host target existing
dengan `devices.ip_address` diperiksa sebelum membaca API. Worker hanya membaca
DHCP/ARP dan menyimpan snapshot sukses lengkap, tanpa alert/notification jobs.
Polling lokal 30 detik, batas gap 120 detik; health menyatakan observasi masih
segar, bukan semua perangkat online. Jangan menjalankan poller kedua untuk router
yang sama bersamaan dengan inventory scheduler existing. Histori lama tanpa
coverage identitas tidak diberi hostname/MAC secara retroaktif.

```sh
flow_compose build flow-inventory
flow_compose up -d flow-inventory
flow_compose exec -T flow-inventory python -m backend.app.bandwidth.inventory_worker health
```

Worker ini opt-in, memerlukan `BANDWIDTH_INVENTORY_TARGET_NAME`; konfigurasi
multi-target JSON tetap ada tanpa menjalankan target Regional. `--api-host`
adalah override transport yang harus diverifikasi operator terhadap router yang
dipilih. Bila VPN terputus/IP Mac berubah, periksa kembali IP, bind port, target
router dan API sebelum restart. Jangan menghapus spool atau mengubah policy
stream existing untuk mengatasi gangguan koneksi.

Polling live berikutnya mencatat 107 perangkat; API inventory mengembalikan 107
baris dan API top usage mengembalikan 59 baris dengan `client_id` teridentifikasi
pada pemeriksaan akhir. Nilai berubah mengikuti observasi, bukan daftar statis.

Perbaikan live: baris kosong pemisah batch dari file transport GoFlow2 tidak lagi
disimpan sebagai malformed record. Baris nonkosong malformed dan partial terakhir
tetap dipertahankan agar ditolak terukur oleh worker.
Pemeriksaan lanjutan menemukan objek JSON menempel dalam satu baris. Transport
file decoder menulis payload dan separator secara terpisah; default listener kini
`netflow://:2055?count=1&workers=1` agar stdout tidak terinterleave antar worker.
Jangan menaikkan paralelisme stdout tanpa transport yang menjaga batas record.
Sumber upstream: [file transport](https://github.com/netsampler/goflow2/blob/main/transport/file/transport.go)
dan [opsi listener](https://github.com/netsampler/goflow2/blob/main/docs/performance.md).
Record malformed sebelum perbaikan sudah ditolak dan tidak dipulihkan; interval
itu tidak boleh dipakai sebagai window validasi transfer.
Setelah restart dengan satu worker, counter `invalid_json` pada stream aktif tetap
159 selama pemeriksaan lanjutan dengan flow baru bertambah. CLI menunjukkan 185
untuk seluruh router karena mencakup 26 penolakan pada stream awal. Checkpoint
akhir mencatat 38.445 accepted flow, pending segment nol, worker policy aktif
hidup, serta collector/inventory/API/UI/MySQL sehat. Ini observasi terbatas,
bukan pembuktian kelengkapan UDP.

Validasi source akhir: suite backend cepat 393 lulus, 2 row-lock khusus MySQL
dilewati, 148 deselected. Suite MySQL terpisah CLI/ingestion 19 lulus dan inventory
worker 3 lulus; database tes dibersihkan. Ruff lint/format, mypy modul berubah,
Compose config, build image dan diff whitespace lulus.

Yang belum selesai: transfer upload/download berukuran diketahui dari perangkat
LAN kantor, pemeriksaan atribusi identitas sepanjang window transfer, dan bukti
kelengkapan/kehilangan UDP. Status laporan tetap `completeness=unverified`.
Bagian berikut mencatat prosedur dan preflight historis 15 Oktober.

## Prasyarat lokasi collector

Pada preflight 15 Oktober 2026, Head Office adalah device ID **2** di database.
Alamat API targetnya adalah WAN router, sedangkan tujuan IPFIX yang terbaca pada
router adalah `192.168.1.172:2055`. Traffic Flow aktif, IPFIX dipilih, sampling
nonaktif, active timeout 30 menit dan inactive timeout 15 detik. Tidak ada
perubahan konfigurasi router yang dilakukan oleh implementasi ini.

Akses API melalui VPN belum membuktikan router bisa mengirim UDP kembali ke
collector. Jika Mac berada di luar kantor, jangan menganggap IP LAN lama masih
mengarah ke Mac. Verifikasi rute penerimaan di lokasi collector yang akan dipakai.
Alternatif penempatan collector tetap di kantor dapat direncanakan terpisah.

`sampler_address` yang terlihat di GoFlow2 lama tidak cocok dengan asumsi IP LAN
exporter saat preflight; penyebabnya belum terverifikasi. Jangan menyalin IP WAN,
IP LAN, atau alamat yang terlihat tersebut ke policy tanpa memverifikasi sumber
dan jalurnya. Jangan menonaktifkan pengecekan exporter untuk meloloskan data.
Contoh ID **1** dalam policy generik juga bukan ID Head Office instalasi ini.

## Kesiapan schema dan konfigurasi

1. Sediakan backup lokal privat sebelum migrasi. Backup aktivasi ini tercatat di
   `backup/bandwidth-activation/latest-backup.json` dengan ukuran dan SHA-256.
   Jangan memasukkan dump SQL atau credential ke Git maupun log aplikasi.
2. Pada instalasi ini, schema tanpa `alembic_version` sudah dibandingkan dengan
   model sebelum bandwidth: tidak ada drift. Backup dipulihkan ke MySQL disposable,
   lalu adopsi baseline `20260923_0030`, upgrade ke `20261015_0033` dan schema check
   lulus. Jumlah record pada 23 tabel existing tetap sama. Prosedur yang sama sudah
   diterapkan ke DB project. Ini bukan izin untuk `stamp` database lain tanpa
   pemeriksaan schema dan backup yang setara.
3. Tinjau policy sendiri untuk Head Office: router ID, exporter, subnet, interface
   LAN/WAN dan jaringan yang dikecualikan. Contoh interface 13/10 berasal dari
   eksperimen sebelumnya; verifikasi lagi sebelum aktivasi di jalur baru.
4. Set variabel overlay yang dibutuhkan: `BANDWIDTH_ROUTER_ID`,
   `BANDWIDTH_FLOW_POLICY_PATH`, `BANDWIDTH_LISTEN_ADDRESS`, `BANDWIDTH_LISTEN_PORT`
   dan `GOFLOW2_IMAGE` yang dipin. File policy harus terbaca UID 10001 di worker;
   policy tidak berisi credential. Credential tetap di mekanisme environment
   project existing. Batasi listener hanya pada jalur exporter yang ditinjau.
5. Untuk atribusi MAC/hostname, aktifkan `BANDWIDTH_INVENTORY_ENABLED` pada runtime
   monitoring yang memang menjalankan koleksi Head Office. Polling kedua router
   tidak berarti keduanya diaktifkan sebagai exporter bandwidth. Jangan menyalakan
   worker notifikasi sebagai bagian uji transfer ini.

Overlay opsional berada pada `docker-compose.bandwidth.yml`. Supaya
perintah di bawah memakai file Compose yang konsisten, definisikan fungsi lokal:

```sh
flow_compose() {
  docker compose -f docker-compose.yml -f docker-compose.bandwidth.yml --profile bandwidth "$@"
}
flow_compose config --quiet
flow_compose build flow-collector flow-worker
```

`config --quiet` tidak memverifikasi penerimaan UDP. Health collector memeriksa
manifest spool dan binding router sebelum worker dimulai; health worker memeriksa
heartbeat/binding policy. Keduanya belum membuktikan traffic lengkap atau benar.

## Cutover dan rollback collector

Hanya lakukan setelah prasyarat di atas terpenuhi dan semua image sudah dibangun.
Jangan menjalankan dua listener pada alamat/port yang sama.

```sh
docker stop --time 15 mikrotik-netflow
flow_compose up -d flow-collector flow-worker
flow_compose ps
flow_compose exec -T flow-worker python -m backend.app.bandwidth.diagnostics status
```

Collector lama tetap disimpan untuk rollback; jangan hapus container/image atau
mapping lamanya. Jika deployment baru gagal, hentikan collector baru dahulu,
biarkan worker menghabiskan backlog jika sehat, lalu hentikan worker dan mulai
collector lama kembali:

```sh
flow_compose stop flow-collector
# Periksa backlog sebelum menghentikan worker, bila worker masih sehat.
flow_compose exec -T flow-worker python -c "from pathlib import Path; p=Path('/var/lib/bandwidth-spool'); print({'ready':sum(1 for _ in p.glob('*.ready')), 'open':sum(1 for _ in p.glob('*.open'))})"
flow_compose stop flow-worker
flow_compose stop flow-inventory
docker start mikrotik-netflow
```

Backlog drained berarti file `.ready`/`.open` dan checkpoint pending sama-sama
kosong. Jika worker tidak sehat atau masih ada `.open`, pertahankan volume untuk
recovery; jangan membuang file demi mencapai nol. Rollback listener bisa dilakukan
lebih dahulu bila perlu, dengan mencatat periode data yang belum di-ingest.
Jangan `down -v` atau downgrade schema untuk rollback collector. Decoder yang
restart bisa menunggu template IPFIX kembali; catat jeda ekspor/penerimaannya.

## Tooling penerimaan yang tersedia

CLI berikut hanya membaca database. `baseline` menulis satu file JSON privat
secara eksklusif, sehingga file window sebelumnya tidak tertimpa. Tidak ada
perintah CLI yang mengubah router, meng-commit data DB, atau menghapus spool.

```sh
# Dalam worker Compose: policy diambil dari environment yang sama dengan ingestion.
flow_compose exec -T flow-worker python -m backend.app.bandwidth.diagnostics status
flow_compose exec -T flow-worker python -m backend.app.bandwidth.diagnostics baseline --device-ip DEVICE_IP --output /var/lib/bandwidth-spool/transfer-baseline.json

# Jalankan transfer berukuran diketahui dari perangkat tersebut, lalu tunggu ekspor.
flow_compose exec -T flow-worker python -m backend.app.bandwidth.diagnostics verify --baseline /var/lib/bandwidth-spool/transfer-baseline.json --download-bytes PAYLOAD_BYTES --tolerance-bps 500
```

Untuk CLI lokal di luar Docker, letakkan `--policy /path/to/reviewed-policy.json`
**sebelum** subcommand, dan gunakan konfigurasi DB existing. Gunakan nama baseline
baru untuk setiap percobaan. Flag `--upload-bytes` dapat dipakai sendiri atau
bersama `--download-bytes`; jumlah yang diharapkan harus positif.

- `status`: heartbeat/status per stream, kecocokan policy, accepted/rejected
  counters, checkpoint pending dan ID/waktu receipt flow terakhir yang tersimpan.
  Counter ber-scope seluruh stream router dan menggunakan checkpoint persisten,
  bukan menghitung ulang seluruh raw history. Ini diagnostik manual, bukan endpoint
  polling health berfrekuensi tinggi. Status worker hidup tidak membuktikan ada
  UDP terbaru.
- `baseline`: merekam router, digest policy, IP perangkat, timestamp dan posisi
  flow committed. IP harus berada pada LAN policy dan worker yang cocok harus hidup.
- `verify`: menghitung flow baru setelah cursor untuk router, IP dan policy yang
  sama. Mengulang verify tidak menambah hitungan. Router lain, IP lain atau stream
  dengan policy lain tidak dimasukkan. Counter/timestamp tetap integer/string
  desimal, tanpa float.

`500` basis point adalah toleransi 5%. Kriteria memakai integer exact dan batas
inklusif. Exit code `0` berarti worker hidup untuk status, baseline tersimpan,
atau perbandingan transfer dalam toleransi. Exit `1` berarti status tidak sehat
atau pemeriksaan gagal; exit `2` berarti transfer di luar toleransi. Tidak ada
raw record, credential, atau connection exception yang dicetak oleh CLI.

## Menafsirkan transfer uji

Catat ukuran payload, IP perangkat, rute keluar, waktu mulai/akhir dan arah uji.
Gunakan koneksi baru dan minimalkan aktivitas latar perangkat. Saat melalui VPN,
pastikan transfer benar-benar memakai egress Head Office. Tunggu record flow
selesai diekspor; polling laporan tidak mempercepat active/inactive timeout router.

IPFIX menghitung byte jaringan; ukuran file biasanya hanya payload aplikasi.
Header, ACK, TLS, retransmisi dan traffic latar bisa membuat total berbeda.
`flows_started_before_baseline` menunjukkan record terlambat yang sudah mulai
sebelum baseline dan dapat mencemari window. Jangan menaikkan toleransi hanya
untuk membuat hasil lulus; ulangi window yang lebih terkontrol bila perlu.

Verdict `within_tolerance` hanya menyatakan perbandingan window ini. Seluruh hasil
tetap `completeness=unverified`: satu transfer tidak membuktikan tidak ada paket
UDP hilang/duplikat, kecocokan identitas untuk seluruh waktu, atau dukungan
IPv6/VPN/port forwarding. Cek arah upload/download, daily bytes, histori identitas,
backlog/rejection counters dan beban router sebelum menerima aktivasi operasional.

## Status sesi implementasi

Catatan historis 15 Oktober (digantikan pembaruan 19 Oktober di atas):
cutover tidak dijalankan, router tidak diubah dan Regional Office tidak disentuh.
Sesudah pengguna menjelaskan sedang di luar kantor, uji live ditunda. Docker daemon
juga tidak tersedia pada pemeriksaan terakhir, sehingga tes MySQL untuk CLI baru
dan cleanup container disposable `codex-bandwidth-adoption-test` belum bisa
dikonfirmasi ulang. Setelah Docker tersedia, hentikan hanya container disposable
tersebut bila masih ada; opsi `--rm` saat pembuatannya akan membersihkan container
dan volume anonimnya. Backup privat tetap disimpan. Jangan menghentikan layanan
project/layanan lain tanpa memeriksa pemakaian terbarunya.
