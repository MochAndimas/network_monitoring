# Penerimaan dan rollback bandwidth

Mulai dari [panduan konfigurasi](bandwidth.md). Catatan instalasi Head Office dan
perbaikan publish UDP ada di [arsip aktivasi Oktober 2026](../history/bandwidth-activation-2026-10.md).

## Prasyarat

- Schema sudah sampai `20261015_0033`; backup privat tersedia sebelum migrasi.
- Router ID, interface, subnet dan exporter policy sudah diverifikasi.
- Router dapat mengirim UDP ke IP/port host collector; akses API saja tidak cukup.
- Satu listener pada IP/port tersebut, satu inventory poller per router.
- Policy/stream lama tidak diedit; volume baru hanya untuk perubahan policy yang ditinjau.

```sh
flow_compose() {
  docker compose "$@"
}
make bandwidth-config
make bandwidth-status
```

Health collector memverifikasi manifest spool; health worker memeriksa stream,
policy dan freshness heartbeat. Inventory health memeriksa observasi terbaru.
Tetap periksa receipt dan accepted flow yang bertambah, bukan health saja.

## Uji transfer terukur

1. Pilih perangkat LAN dengan IP diketahui, rute WAN yang sesuai policy, dan
   aktivitas latar minimal. Jangan memakai IP VPN sebagai perangkat LAN tanpa
   policy interface/rute yang memang mendukungnya.
2. Buat baseline **sebelum** memulai koneksi transfer baru:

```sh
flow_compose exec -T flow-worker python -m backend.app.bandwidth.diagnostics baseline --device-ip DEVICE_IP --output /var/lib/bandwidth-spool/transfer-01.json
```

3. Lakukan download/upload berukuran diketahui dari perangkat tersebut. Catat
   payload, arah, waktu mulai/selesai, IP dan rute keluarnya.
4. Tunggu ekspor router (inactive/active timeout), lalu verifikasi:

```sh
flow_compose exec -T flow-worker python -m backend.app.bandwidth.diagnostics verify --baseline /var/lib/bandwidth-spool/transfer-01.json --download-bytes PAYLOAD_BYTES --tolerance-bps 500
```

Gunakan `--upload-bytes` untuk upload, atau keduanya bila window mengukur dua arah.
Baseline bersifat eksklusif/private; gunakan nama baru untuk window berikutnya.
Untuk CLI lokal, `--policy /path/to/policy.json` diletakkan sebelum subcommand.

`500` basis point berarti toleransi 5% dengan aritmetika integer exact. Byte IPFIX
menghitung trafik jaringan, sedangkan ukuran file biasanya payload aplikasi;
header, ACK, TLS, retransmisi dan background traffic dapat membuat selisih.
`flows_started_before_baseline` menandai record lama yang mencemari window.
Jangan menaikkan toleransi hanya supaya hasil lulus. Ulangi window terkontrol.

Exit CLI: 0 untuk health/hasil sesuai toleransi, 1 untuk kegagalan pemeriksaan,
2 untuk hasil di luar toleransi. Diagnostics membaca DB; baseline hanya menulis
satu file JSON tanpa mengubah router/checkpoint. Counter status ber-scope seluruh
stream router, termasuk stream historis yang sudah berhenti.

`within_tolerance` hanya membuktikan kesesuaian window itu. Status laporan tetap
`completeness=unverified`; satu transfer tidak membuktikan seluruh UDP lengkap,
bebas duplikasi, seluruh identitas benar, atau mendukung IPv6/VPN/port forwarding.
Periksa kedua arah, alokasi harian, identitas dan counter penolakan/backlog.

## Rollback atau pemulihan listener

Hentikan penerimaan dulu; biarkan worker sehat menghabiskan segmen yang sudah
sealed sebelum worker dihentikan. Periksa kedua sisi backlog:

```sh
flow_compose stop flow-collector
flow_compose exec -T flow-worker python -m backend.app.bandwidth.diagnostics status
flow_compose exec -T flow-worker python -c "from pathlib import Path; p=Path('/var/lib/bandwidth-spool'); print({'ready':sum(1 for _ in p.glob('*.ready')), 'open':sum(1 for _ in p.glob('*.open'))})"
```

Drained berarti pending checkpoint, `.ready`, dan `.open` sama-sama kosong. Jika
worker tidak sehat, pertahankan volume untuk recovery. Jangan menghapus segmen
agar angka tampak nol. Untuk masalah publish port, setelah drain:

```sh
flow_compose rm -f flow-collector
flow_compose up -d --no-build --no-deps flow-collector
```

Ini hanya mengganti container collector, tetap memakai volume/manifest dan image
yang sama. Pastikan listener lama sudah dilepas, template baru diterima dan flow
committed bertambah. Restart decoder dapat menimbulkan jeda sampai template muncul.

Untuk kembali ke deployment lama, hentikan collector baru dahulu, drain/hentikan
worker dan inventory, lalu nyalakan listener lama yang memang masih tersedia.
Kembalikan target router bila IP/port lama berbeda dan jalurnya masih reachable.
Jangan menyalakan dua listener pada alamat/port yang sama. Jangan `down -v`, reset
DB, downgrade schema, atau restart seluruh Docker sebagai langkah pertama.
