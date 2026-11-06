# Inventaris klien bandwidth

Implementasi ini menyimpan identitas IPv4/MAC/hostname dan histori observasi IP
di MySQL existing. Konfigurasi ada di [panduan operasi](bandwidth.md).
Inventory dapat dijalankan scheduler existing atau worker mandiri satu router;
jangan menjalankan keduanya untuk router yang sama.

## Model dan batas transaksi

- `bandwidth_clients`: identitas per pasangan router + MAC. Hostname nonkosong
  terbaru diperbarui; `custom_name` tetap dipertahankan. Klien tidak otomatis
  menjadi target polling/alert dalam tabel `devices`.
- `bandwidth_client_ip_history`: interval pengamatan IP, sumber DHCP/ARP, dan
  satu binding aktif per router/IP. Ada index terpisah untuk binding aktif agar
  sinkronisasi tidak perlu memindai seluruh histori.
- `bandwidth_inventory_states`: timestamp snapshot berhasil terbaru serta jumlah
  binding, IP ambigu dan baris identitas invalid. Jumlah binding bukan indikator
  jumlah perangkat online; satu MAC juga dapat mempunyai beberapa IP.

Collector memakai ulang pembacaan DHCP dan ARP existing. Ia mengembalikan
`InventoryMetricBatch`, subclass list yang membawa snapshot. Service
`persist_metrics` menyimpan identitas dalam transaksi yang sama dengan metrik,
baik melalui scheduler maupun run manual. Tidak ada commit dari service
sinkronisasi; rollback caller membatalkan kedua jenis data.

Write diserialisasi memakai row lock router pada MySQL. Pembacaan current-state
memakai locking read agar konsisten meskipun transaksi REPEATABLE READ sudah
memiliki snapshot lama dari pembacaan metrik. Snapshot stale/replay tidak mengubah
histori. Lock beberapa router diambil menurut urutan ID tetap.

Semua timestamp inventaris menggunakan integer epoch nanodetik UTC; jangan
mencampurnya langsung dengan datetime metrik existing yang naive WIB.

## Kualitas identitas

DHCP hanya menerima lease `bound`. ARP hanya menerima status `reachable` atau
`permanent`. MAC harus valid, unicast, dan bukan zero address; IPv6 tidak masuk
ke pipeline IPv4 ini. Jika satu IP mempunyai MAC berbeda dalam snapshot yang sama,
IP ditandai ambigu dan tidak dipilih salah satu pemiliknya.

Poll yang berdekatan dengan pemilik sama dianggap kontinu sampai batas
`BANDWIDTH_INVENTORY_MAX_GAP_SECONDS` (default 120 detik). Ini inferensi dari
observasi, bukan waktu assignment DHCP yang pasti. Sesuaikan dengan interval
scheduler; nilai lebih besar memperluas asumsi kontinuitas.

IP yang menghilang/ambigu, berpindah pemilik, atau muncul setelah gap besar
mengakhiri interval lama tepat satu nanodetik sesudah observasi terakhir.
Interval baru mulai pada observasi baru. Gap tidak diisi dengan tebakan.
Kegagalan pembacaan API tidak pernah disimpan sebagai snapshot kosong yang sukses.

Resolver hanya mengembalikan identitas bila seluruh start/end flow tercakup satu
interval pengamatan. Flow sebelum discovery, sesudah observasi terakhir, pada
gap, atau melintasi pergantian pemilik tetap belum terpetakan. Worker inventory
mandiri merekonsiliasi flow NULL ketika observasi tambahan sudah cukup, dengan
pemindahan byte harian dalam transaksi yang sama. Gap dan histori ambigu tetap
tidak ditebak; lihat kontrak [reporting](bandwidth-reporting.md).

DHCP bound dan ARP permanent tidak menjamin perangkat online. MAC random juga
tetap dianggap identitas berbeda; belum ada penggabungan identitas otomatis.

## Aktivasi

Default fitur **nonaktif** pada settings umum. Overlay bandwidth mengaktifkan
worker inventory mandiri secara eksplisit. Urutan deployment:

1. Backup DB; pastikan schema mengikuti [panduan operasi](bandwidth.md).
2. Pilih satu collector inventory: integrasi scheduler existing atau worker
   mandiri. Untuk mode mandiri pilih target JSON dan policy router yang cocok.
3. Set `BANDWIDTH_INVENTORY_ENABLED=true` untuk integrasi scheduler, atau jalankan
   service opt-in `flow-inventory` sesuai overlay. Batas gap default 120 detik.
4. Build/restart hanya runtime collector inventory yang dipilih dan tunggu
   snapshot MikroTik sukses. Polling mandiri maksimal separuh batas gap.
5. Periksa state/histori dan endpoint `/bandwidth/{router_id}/clients` atau
   inventaris UI Live Monitoring. Jumlah binding bukan jumlah perangkat online.

Untuk menonaktifkan sinkronisasi, set flag false dan restart worker; data histori
tetap disimpan. Timestamp terakhir membuat umur data bisa dinilai oleh consumer.
Downgrade schema menolak tabel inventaris berisi data; ekspor dan pensiunkan data
secara eksplisit terlebih dahulu. FK ke `devices` mencegah router dihapus selama
masih mempunyai histori; nonaktifkan target sebagai alternatif operasional.

## Pengujian

```sh
venv/bin/python -m pytest tests/services/test_bandwidth_inventory.py tests/services/test_bandwidth_collector.py tests/services/test_bandwidth_inventory_migration.py -q
```

Fixture inventaris dapat memakai `BANDWIDTH_TEST_DATABASE_URL` dengan driver
`mysql+aiomysql` untuk MySQL 8.4. **Gunakan database disposable khusus tes**:
fixture membuat dan menghapus tabel aplikasi. Tanpa variabel ini, test memakai
SQLite sementara dan test row-lock MySQL dilewati.

Gate migrasi MySQL: satu Alembic head, upgrade penuh, `alembic check`, downgrade
ke `20260923_0030` pada tabel baru kosong, lalu upgrade ulang. Pengujian produksi
tetap perlu memeriksa izin DHCP/ARP pada target nyata dan memantau latensi siklus.
