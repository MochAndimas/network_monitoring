# IMP-007 — agregasi Live Monitoring grup

Status: Done, implementasi dan validasi lokal, 1 Oktober 2026.

## Kontrak dan desain

`GET /metrics/history/group?group=voip|ruijie` memakai read model khusus: repository mengerjakan query terbatas, service menyusun kontrak dan budget, hook React Query mengatur polling/cancellation, dan komponen ringkasan menyajikan scope/freshness/detail.

- Hanya perangkat aktif. VoIP berdasarkan tipe; Ruijie berdasarkan tipe atau nama (case insensitive). API menyediakan filter `site`, `device_type`, `device_id`, `metric_name`, `status`.
- Halaman perangkat berurutan berdasarkan ID: default 20, maksimum 50. Metadata memuat total, offset, has_more dan perangkat pada halaman. Status/freshness/counts berlaku untuk halaman ini.
- Mode live memakai 24 jam terakhir; range wajib memiliki tanggal berurutan, maksimum 31 hari. Tanggal aware dinormalisasi ke WIB; tanggal frontend memakai offset +07:00.
- Maksimum 64 nama metrik dan 8 seri metrik pada overview. Metric filter dapat memilih satu seri. Default 50 sampel terbaru per pasangan, maksimum input 200; budget bersama maksimum 2.000 item trend. Urutan timestamp dan ID deterministik.
- History maksimal 100 item; snapshot default 10, maksimum 100 dengan pagination. Snapshot adalah kondisi terbaru, independen dari rentang history. History yang dibatasi melaporkan sampling; jumlahnya bukan hitungan seluruh history database.
- Nilai teks dibatasi 256 karakter. JSON maksimum 1 MiB; bila perlu, service mengurangi sampel secara merata per pasangan sampai budget terpenuhi. Batas dan sampling dinyatakan di metadata dan UI.
- Trend adalah sampel terbaru, bukan cakupan lengkap seluruh rentang waktu. Halaman/detail perangkat tetap tersedia untuk investigasi. Perangkat tanpa data dan data stale ditampilkan eksplisit.
- Frontend grup memakai satu query per refresh 15 detik, AbortSignal saat filter berubah/unmount, dan retry hanya query yang aktif. Endpoint/detail individual tetap tersedia. Identitas seri memakai device_id agar nama duplikat tidak menyatukan data.

Tidak ada migrasi, dependency atau konfigurasi baru. Query trend membatasi ID per pasangan sebelum UNION, dengan batch maksimal 64, memakai indeks history yang sudah ada.

## Bukti validasi

- Backend quality gate: 368 passed, 20 MySQL tests skipped pada run biasa; Ruff, mypy, Pyright dan Bandit lulus. API grup memiliki 12 tes untuk scope, pagination, validasi parameter/tanggal, timezone, fairness Unicode/payload dan sampling.
- MySQL fixture terisolasi: 20 tes integrasi lulus, termasuk timestamp seri yang sama dan scope grup.
- Frontend: 15 file / 35 tes lulus, ESLint dan TypeScript lulus. Tes hook memverifikasi satu query grup, cancellation dan range; tes halaman memverifikasi detail, freshness, pagination dan retry tanpa query global yang nonaktif.
- Build production Docker backend/frontend berhasil dan diterapkan lokal. Browser lokal terverifikasi: grup 18 VoIP, freshness, tautan detail, grafik dan tabel tampil; tidak ada error console. Tab verifikasi ditutup dan container MySQL fixture dihentikan/auto-remove. Tidak ada run CI remote atau deployment lingkungan lain.

## Benchmark dan batas pengukuran

Bukti mentah: [imp007-group-benchmark.json](imp007-group-benchmark.json). Reproduksi menggunakan `scripts/benchmark_metric_group.py` pada MySQL fixture kosong dengan nama database berakhiran `_group_fixture` dan API key sintetis eksplisit.

MySQL 8.4.11, 100 perangkat × 8 metrik × 120 sampel = 96.000 baris history. Baseline satu dashboard: 100 HTTP request, 600 SELECT, total JSON 32.343.917 byte. Empat dashboard memproyeksikan 400 request per refresh. Implementasi baru diuji tiga siklus empat dashboard bersamaan: 4 request / 48 SELECT per siklus (12 SELECT per dashboard), median 341,45 ms, p95 377,07 ms, maksimum 379,24 ms; payload maksimum 397.356 byte. Gate 2 detik/request, 60 SELECT/empat dashboard dan 1 MiB/response lulus.

Baseline mengambil seluruh 100 perangkat; respons baru memuat halaman 20 perangkat. Ini pengurangan beban melalui kontrak pagination, bukan klaim mengirim volume data identik. Baseline hanya menghitung fan-out perangkat, tidak memasukkan request konteks global tambahan. HTTP memakai aplikasi FastAPI nyata dengan transport ASGI dalam proses sehingga tidak memasukkan latensi jaringan. Fixture sintetis dan empat dashboard bukan sertifikasi kapasitas produksi. Benchmark tidak mengirim Telegram atau menjalankan scheduler.
