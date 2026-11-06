# Backend bandwidth

Panduan operasi utama: [docs/ops/bandwidth.md](../../../docs/ops/bandwidth.md).

Domain murni tetap terpisah dari proses, database dan konfigurasi global:

| Modul | Tanggung jawab |
| --- | --- |
| `contracts`, `normalizer`, `classifier` | Validasi/klasifikasi IPv4 IPFIX immutable |
| `daily` | Alokasi byte exact pada batas hari WIB |
| `discovery` | Observasi DHCP/ARP konservatif |
| `ingestion_config` | Policy JSON ketat dan digest immutable |
| `spool` | Manifest, lock, checksum, fsync, quota, recovery |
| `collector`, `collector_health` | Supervisi GoFlow2 dan readiness tanpa dependency DB |
| `ingestion_runtime`, `worker` | Checkpoint transaksional, retry, health ingestion |
| `inventory_worker` | Polling satu router, snapshot dan rekonsiliasi terikat waktu |
| `health` | Kontrak freshness bersama, termasuk penolakan timestamp masa depan |
| `validation`, `diagnostics` | Baseline transfer dan pemeriksaan read-only |

Transaksi aplikasi berada di `services/bandwidth_*`, query penyimpanan di
`repositories/bandwidth_*`, dan API di `api/routes/bandwidth.py`.
Flow tidak dideduplikasi berdasarkan tuple jaringan. Replay spool menggunakan
stream/segment/offset; atribusi client boleh diperbarui hanya oleh rekonsiliasi
berdasarkan interval bukti, bersama pemindahan total harian yang atomik.

Kontrak normalisasi:

- Hanya tipe `IPFIX` dan IPv4. Field NAT menerima dotted IPv4 atau delapan digit
  hex dari custom mapping yang diuji. Tidak menebak format Base64.
- NAT absent/null/kosong/zero berarti tidak tersedia. Download routed dapat memakai
  destination langsung jika berada dalam LAN. Download NAT tanpa alamat internal
  yang valid ditolak; tidak ada korelasi port yang spekulatif.
- Byte, paket, interface dan timestamp wajib integer JSON nonnegatif; boolean,
  float, string numerik dan field wajib yang hilang ditolak. Byte nol ditolak.
- Counter/timestamp dibatasi signed BIGINT, interface dibatasi uint32. Timestamp
  epoch nanodetik dipertahankan persis; start/end harus positif dan berurutan.
  Clock skew terhadap receipt dipertahankan untuk diperiksa layer ingestion.
- Unknown fields diabaikan agar metadata GoFlow2 tambahan tetap kompatibel.
- Hasil immutable; input tidak diubah. Alasan error stabil dan tidak memuat raw data.

Lihat [kontrak reporting](../../../docs/ops/bandwidth-reporting.md) untuk API,
alokasi hari dan rekonsiliasi. Nilai byte/ns pada API berbentuk string desimal;
completeness tetap unverified. Exporter diverifikasi terhadap sumber yang terlihat
di decoder, bukan diturunkan dari IP perangkat klien.

```sh
venv/bin/python -m pytest tests/services/test_bandwidth_*.py -m 'not mysql' -q
```
