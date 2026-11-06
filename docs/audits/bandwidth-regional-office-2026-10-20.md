# Aktivasi bandwidth Regional Office — 20 Oktober 2026

## Implementasi

- Router RO didaftarkan sebagai device MikroTik ID 41 berdasarkan konfigurasi
  `regional-office` existing, dengan IP inventory DB 103.171.153.57.
- Template Compose collector/worker/inventory dipakai ulang melalui YAML anchors.
  Profile `bandwidth-ro` memiliki tiga service suffix `-ro`; port host UDP 2056,
  volume `network_monitoring_bandwidth_ro_v1`, dan policy lokal RO terpisah dari HO.
- Default perintah Make tetap HO. `BANDWIDTH_SITE=ro` memilih layanan dan profile
  RO, termasuk `bandwidth-up/config/status/logs`; nilai site lain ditolak.
- Tidak ada perubahan schema, perhitungan byte, query API, atau komponen frontend.
  Pemilih router UI menggunakan daftar devices existing dan tersedia untuk RO.
- API VPN 10.20.20.1:8728 awalnya menutup sesi karena allowlist berisi alamat
  server 10.20.20.1. Operator menambahkan IP client 10.20.20.10; identity
  `Mikrotik SSKB RO` dan pembacaan DHCP/ARP kemudian berhasil diverifikasi.
- Traffic Flow RO dibackup sebelum aktivasi, kemudian disetel pada bridge-LAN,
  target 10.20.20.10:2056, IPFIX, enabled yes. Target awal kosong dan flow disabled.
  Penambahan target pertama dengan field comment ditolak RouterOS tanpa mutasi;
  percobaan berikutnya tanpa field tersebut berhasil. Timeout/sampling/offload
  dan konfigurasi HO tidak diubah.

## Verifikasi

- ifIndex dari OID router: bridge-LAN 11, ether1-WAN 2. LAN 192.168.88.0/24.
- Tiga layanan RO healthy; collector UDP 2056 terpisah dari HO UDP 2055.
- Exporter aktual RO terlihat sebagai 172.19.0.1 oleh GoFlow2. Sesuai alias yang
  ditinjau dalam policy, tanpa unexpected_exporter rejection.
- Stream RO `5ceeaac0-3a2c-4c0e-bef2-e761e99108d9`; digest
  `0b9c236e6438c4c1eb22791be756d22fd5d07ffdf71c09ecfcfa0d46af7304d7`.
- Accepted RO bertambah dari 194 ke 1429 pada dua pembacaan; receipt terbaru,
  pending segments nol. Rejection interface/private/IPv6 dipertahankan sesuai
  kontrak classifier; tidak mengklaim semua flow merupakan internet usage.
- Inventory RO tersimpan 35 client historis saat pemeriksaan akhir. Ini bukan
  hitungan perangkat online. Laporan harian RO tersedia.
- SQL read-only memverifikasi SUM raw bytes sama dengan SUM daily bytes secara
  terpisah untuk HO dan RO: 54040299754 dan 79743123 pada snapshot pemeriksaan.
- 154 tes bandwidth lulus, 3 skip spesifik environment; tes baru isolasi dua
  router dengan IP/MAC/exporter NAT yang sama juga lulus pada MySQL terpisah.
  Database tes dibuang setelah selesai. Ruff tes baru dan diff whitespace lulus.
- Compose JSON terurai diverifikasi mempunyai port/policy/spool berbeda,
  dependency worker RO hanya pada collector RO dan MySQL, serta endpoint RO
  tanpa fallback API ke Head Office. Semua layanan existing HO tetap healthy.

## Batas verifikasi

Controlled known-size upload/download belum dilakukan; completeness tetap
unverified. IP VPN Mac RO 10.20.20.10 harus dipertahankan/diperbarui pada router
bila lease berubah. Health collector tidak membuktikan kelengkapan UDP.
Rollback dan perintah per site ada pada docs/ops/bandwidth.md; backup router
privat di backup/bandwidth-activation/ro-before-activation.json.
