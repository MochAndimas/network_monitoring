# Laporan penggunaan bandwidth

Agregasi harian, API backend dan tab Bandwidth pada Live Monitoring tersedia.
Konfigurasi ada di [panduan operasi](bandwidth.md). Migrasikan sampai
`20261015_0033` sebelum menjalankan worker/API. Runtime ingestion tetap opt-in.

Untuk cutover, rollback dan baseline transfer terkontrol, lihat
[panduan aktivasi/penerimaan](bandwidth-acceptance.md). Tooling tersedia, tetapi
uji transfer terukur untuk penerimaan operasional belum diselesaikan.

## UI Live Monitoring

Buka **Live Monitoring → Bandwidth**, lalu pilih router MikroTik. Filter tanggal
memakai WIB dan diterapkan setelah tombol **Terapkan periode** ditekan; batasnya
31 hari inklusif. Ringkasan utama dan Top pengguna tetap menampilkan seluruh
perangkat untuk periode itu. Klik nama pada ranking atau inventaris untuk membuka
popup detail penggunaan harian perangkat. Detail memakai query klien terpisah;
overview tidak berganti filter dan posisi ranking tetap. Popup dapat ditutup
dengan **Tutup detail**, Escape, atau klik backdrop. Fokus kembali ke pemicu.
URL `bw_client` membuka popup saat halaman dimuat dan dihapus saat popup ditutup.

Top pengguna memakai pagination server 10 baris; inventaris memakai keyset 10
baris. Pindah router mereset filter klien dan pagination. Query cache mencakup
router, periode, klien dan posisi halaman; tidak memuat seluruh inventaris atau
flow mentah ke browser. Query metrik kesehatan dilepas saat tab Bandwidth aktif.

Periode yang mencakup hari ini diperbarui otomatis setiap 60 detik ketika tab
browser aktif. **Perbarui data** memuat ulang laporan dan inventaris secara manual.
Periode historis tetap dapat berubah ketika flow terlambat diterima. Error setiap
bagian memiliki retry tersendiri; bagian lain tetap bisa digunakan. Tanggal
invalid dapat diperbaiki tanpa meninggalkan halaman.

URL laporan dapat dibagikan, contohnya
`/live-monitoring?tab=bandwidth&device=1&bw_from=2026-10-14&bw_to=2026-10-15`.
Filter klien memakai `bw_client=<id>` dan tetap diverifikasi oleh API untuk router
yang bersangkutan. URL bukan pengganti autentikasi atau pemberian akses baru.

Formatter dan akumulasi memakai BigInt; satuan tampilan KiB/MiB/GiB bersifat
pembulatan untuk keterbacaan. Tooltip angka menyimpan byte utuh dan label
aksesibilitas memakai jumlah byte yang sama. Tidak mengisi hari yang hilang
dengan nol. IP unresolved tidak diberi tombol histori identitas karena IP bisa
dipakai beberapa perangkat bergantian. Waktu update laporan bukan heartbeat
collector, dan last seen inventaris bukan indikator online.

Test komponen/format tersedia lewat `pnpm test`. Smoke test browser sintetis
tersimpan pada `frontend/e2e/bandwidth.spec.ts`; jalankan frontend lokal lalu
`pnpm test:e2e e2e/bandwidth.spec.ts`. Suite itu mengganti API dengan fixture,
tidak memerlukan backend atau login nyata, dan membutuhkan browser Playwright
yang terpasang seperti suite E2E existing. Pemeriksaan memakai URL filter nyata,
isolasi router, lebar mobile 390 px dan dua tema.

## Penyimpanan dan konsistensi

`bandwidth_daily_usage` menyimpan satu baris per router, tanggal WIB dan subjek.
Subjek `c:<id>` menggabungkan penggunaan klien yang sama pada beberapa IP;
`ip:<IPv4>` menyimpan traffic yang belum memiliki cakupan histori identitas.
IP unresolved bukan identitas perangkat: beberapa perangkat bisa memakai IP
yang sama pada waktu berbeda. Tidak ada atribusi ulang otomatis ke MAC terbaru.

Worker memperbarui flow, ringkasan, rejection counter dan checkpoint dalam satu
transaksi dengan lock router existing. Replay checkpoint tidak menambah angka.
Flow terlambat memperbarui tanggal flow, bukan tanggal diterima. Upsert dikelompokkan
dan ditulis maksimal 100 baris per statement; buffer maksimal 1.000 bucket.
API membaca ringkasan dengan prefix primary key `(router_id, day, subject)`,
bukan men-scan flow mentah. Ranking tetap menghitung subjek dalam rentang yang
diminta; rentang dibatasi 31 hari, respons maksimal 200 baris.

MySQL menyimpan counter ringkasan sebagai `DECIMAL(38,0)` sehingga akumulasi dapat
melewati signed BIGINT. Variant SQLite untuk test memakai integer 64-bit dan
tidak menjadi bukti dukungan total di atas batas tersebut. Flow mentah tetap
mengikuti kontrak signed BIGINT dari tahap ingestion.

## Aturan pembagian tanggal

Tanggal selalu Asia/Jakarta (UTC+7). Interval dianggap `[start,end)`; tepat berakhir
di tengah malam tidak menambah penggunaan ke hari berikutnya. Interval berdurasi
nol dialokasikan ke tanggal timestamp itu.

Untuk flow lintas hari, bagian byte pada setiap tanggal dihitung dari selisih
floor kumulatif `total_bytes * elapsed_ns // duration_ns`. Tidak memakai float,
dan jumlah semua bagian selalu sama dengan byte flow, termasuk flow kecil.
`estimated_bytes` menandai seluruh byte dari flow lintas hari karena waktu byte
individual tidak tersedia. Policy publik bernama `proportional_integer_v1`.

## API

Semua endpoint memakai autentikasi API existing dan router harus bertipe
`mikrotik`. Scoping router mengikuti aplikasi existing; belum ada ACL per router.

- `GET /bandwidth/{router_id}/clients?limit=50&after_id=0`: inventaris, nama tampilan,
  MAC, hostname dan waktu observasi. Pagination keyset lewat `next_after_id`.
- `GET /bandwidth/{router_id}/usage/daily?start=2026-10-14&end=2026-10-15`:
  upload/download/total per tanggal, maksimal 31 hari inklusif.
- `GET /bandwidth/{router_id}/usage/top?start=2026-10-14&end=2026-10-15&limit=50&offset=0`:
  subjek diurutkan total menurun dan subjek sebagai tie-breaker; offset maksimal
  10.000. `has_more` menunjukkan masih ada hasil. Hasil dapat bergeser saat ada
  ingestion baru; pagination tidak menjanjikan snapshot lintas request.

Kedua laporan dapat diberi `client_id` untuk filter perangkat yang sudah terpetakan.
Client dari router lain menghasilkan 404. Semua counter byte dan timestamp
nanodetik dikirim sebagai string desimal untuk menjaga presisi JavaScript.
Gunakan `BigInt` ketika frontend menghitung byte; jangan `Number` untuk accounting.

`unresolved_bytes` adalah bagian yang belum punya identitas klien.
`updated_ns` adalah waktu update bucket, bukan waktu traffic terbaru atau bukti
collector aktif. `completeness` selalu `unverified`: UDP bisa hilang atau terduplikasi,
flow bisa terlambat dan jalur IPv6/VPN belum tervalidasi. Hari tanpa baris tidak
menjadi bukti penggunaan nol. DHCP/ARP last_seen juga tidak membuktikan online.

## Migrasi dan backfill

Hentikan worker ingestion selama upgrade/downgrade. `0033` membuat tabel turunan
dan mengisi flow lama secara keyset batch 500; tidak mengubah raw flow/checkpoint.
Backfill flow lintas hari menggunakan allocation v1 yang dibekukan dalam migrasi.
Durasi upgrade bergantung volume histori; lakukan backup dan uji pada salinan DB
sebelum upgrade instalasi yang sudah memiliki traffic. MySQL DDL tidak transaksional;
jika migrasi gagal setelah CREATE, periksa schema/data sebelum menjalankan ulang.

Downgrade menghapus hanya ringkasan turunan. Upgrade berikutnya membangunnya lagi
dari raw flow yang masih disimpan. Retensi otomatis raw flow belum tersedia;
jangan hapus raw flow jika masih membutuhkan kemampuan rebuild lengkap.
# Rekonsiliasi identitas terlambat (19 Oktober 2026)

Worker inventory memanggil rekonsiliasi setelah snapshot sukses. Setiap transaksi
memproses maksimal 500 flow dan melepas lock router antar batch; satu polling
dibatasi 10 batch. Ingestion, snapshot dan rekonsiliasi memakai lock router yang
sama. Hanya flow `client_id IS NULL` yang seluruh rentang waktunya tercakup tepat
satu interval histori IP–MAC yang dipindahkan. Gap, pergantian pemilik, interval
ambigu dan waktu sebelum observasi pertama tetap unresolved.

Dalam satu transaksi, byte upload/download/estimasi dikurangi dari bucket IP,
ditambahkan ke bucket client dan `client_id` flow diperbarui. Bucket IP nol
dihapus. Pengurangan memakai guard nonnegatif; sumber yang tidak cocok menggagalkan
transaksi. Pengulangan dan worker bersamaan tidak menghitung ulang byte.

API top menambahkan `latest_observation` (nama, MAC, timestamp) untuk IP unresolved
yang punya observasi aktif. Ini petunjuk tampilan terpisah, bukan atribusi trafik:
`client_id`, subject IP, unresolved bytes dan perilaku filter tetap sama. UI
menampilkan “Terakhir teramati” beserta waktu dan keterangan pemilik trafik
historis belum terverifikasi. Perangkat tanpa hostname memakai MAC.

Aktivasi Head Office memetakan 41.003 flow tambahan dari 62.569 flow yang sudah
tersimpan. Flow teridentifikasi berubah dari 2.504 ke 43.507. Total harian sebelum
dan sesudah identik: upload 306.666.504 byte, download 3.649.622.137 byte, estimasi
0. Collector tetap menyimpan spool selama worker dijeda; ingestion dan inventory
kemudian dilanjutkan. Backup privat kedua tabel dibuat sebelum perubahan data.
Uji SQLite/MySQL mencakup replay, rollback, konservasi byte lintas hari, overlap,
pergantian pemilik, isolasi router, sumber daily tidak cocok dan concurrency.

