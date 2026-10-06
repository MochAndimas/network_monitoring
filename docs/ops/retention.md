# Retention berbasis checkpoint

Scheduler pusat menjalankan retention sesuai `SCHEDULER_CLEANUP_INTERVAL_HOURS`
(default 24 jam). Lock advisory `cleanup` tetap dipegang sepanjang run, melalui
koneksi terpisah sehingga commit batch tidak melepas kepemilikan job. Agen site
bukan pemilik cleanup. Jangan menjalankan service ini langsung tanpa guard.

## Batas kerja

| Environment | Default | Fungsi |
| --- | --- | --- |
| `RAW_METRIC_RETENTION_DAYS` | 7 | Cutoff raw pada awal hari WIB |
| `RETENTION_SOURCE_BATCH_SIZE` | 1000 | Maksimum ID sumber per transaksi agregasi |
| `RETENTION_ROLLUP_BATCH_SIZE` | 500 | Batas tambahan sumber rollup dan grup summary |
| `RETENTION_ARCHIVE_BATCH_SIZE` | 500 | Batas tambahan sumber archive |
| `RETENTION_DELETE_BATCH_SIZE` | 1000 | Maksimum ID sasaran setiap delete |
| `RETENTION_MAX_BATCHES_PER_PHASE` | 100 | Maksimum batch per fase per run |

Source/delete batch divalidasi 1–10.000; jumlah batch 1–1.000. Limit sumber aktual
adalah minimum source batch dan batas rollup/archive. Summary membaca satu hari
WIB dan mem-page grup site/type, maksimum minimum source batch dan rollup batch.
Bootstrap checkpoint summary juga terbatas. Penghapusan summary usang mempunyai
budget fase tersendiri. Alert, incident, collector telemetry, snapshot perangkat
nonaktif, sesi auth dan login attempt memakai delete terbatas yang sama.

Budget membatasi baris sumber yang diagregasi dan ID yang dimutasi, bukan batas
waktu SQL yang mutlak. Discovery bucket dan agregasi summary dapat memeriksa lebih
banyak baris lewat indeks. Lock wait, jumlah perangkat/grup, lebar nilai teks,
IO dan beban database tetap memengaruhi durasi. Untuk backlog besar, sesuaikan
interval dan budget berdasarkan pengukuran; job sukses dapat masih menyisakan
backlog untuk run berikutnya.

## Integritas, retry dan metrik terlambat

Penulis metrik melalui `MetricRepository` dan retention sama-sama mengunci baris
perangkat sebelum membaca sumber. Retention mengambil ID secara ascending melalui
locking read, kemudian menghitung agregat hanya dari ID tersebut. Agregat dan
checkpoint `(count, max ID, latest checked_at)` disimpan dalam transaksi yang sama.
Setiap batch berikutnya hanya menggabungkan ID yang melampaui checkpoint bucket.

Rollup memakai bucket perangkat/hari. Archive memakai perangkat/hari/nama metrik/
status yang dinormalisasi/unit. Metrik dengan checked_at lama tetapi ID baru adalah
late arrival dan digabung sekali, termasuk sesudah sebagian raw sudah dihapus.
Rata-rata memakai jumlah sampel numerik; nilai archive terbaru menggunakan urutan
checked_at lalu ID. Checkpoint tidak diperkecil ketika raw dipangkas.

Delete raw wajib memenuhi semuanya: melewati cutoff, tercakup checkpoint rollup
serta archive, kedua agregat ada, dan ID tidak direferensikan latest snapshot.
Seleksi dan delete memakai batas ID eksplisit; kondisi diperiksa ulang saat delete.
Snapshot perangkat nonaktif baru dikompaksi sesudah fase raw. Raw yang sebelumnya
dilindungi snapshot tersebut dapat dibersihkan pada run berikutnya.

Jika proses gagal/cancel sebelum commit, batch aktif di-rollback; batch yang sudah
commit bertahan. Jalankan kembali job dengan guard yang sama: checkpoint menentukan
kelanjutan, tanpa cursor dalam memori yang harus dipulihkan. Fase summary menyimpan
offset grup per hari; perubahan rollup mereset offset dan menandai hari dirty.
Hari selesai dirotasi dari yang paling lama diperbarui untuk merekonsiliasi perubahan
metadata site/type. Summary bersifat eventually consistent, bukan snapshot atomik
seluruh backlog; grup usang dipangkas secara terbatas.

## Kontrak sumber dan pemulihan

Raw adalah append-only: koreksi/backfill harus membuat sampel baru melalui repository.
Jangan mengedit/menghapus raw, mengganti ID, atau menaikkan checkpoint secara manual.
Fingerprint berubah karena append yang sah dan diperbarui bersama agregat. Fingerprint
legacy/null pada agregat yang sudah ada, atau checkpoint yang kehilangan agregat,
menghentikan pemrosesan terkait sebelum pruning. Implementasi tidak mendeteksi semua
perubahan SQL di luar aplikasi atau korupsi arbitrer pada checkpoint.

Untuk state yang tidak konsisten, hentikan cleanup dan pulihkan agregat + checkpoint
bersama dari backup konsisten, atau rebuild bucket dari sumber lengkap yang telah
diverifikasi. Raw yang tersisa setelah pruning bukan sumber lengkap; menghapus marker
saja tidak boleh dipakai sebagai prosedur rebuild. Verifikasi jumlah/numeric count,
rata-rata, rentang waktu dan nilai terakhir sebelum mengaktifkan cleanup kembali.

`cleanup_monitoring_data(commit=True)` adalah jalur operasional, dengan session khusus
tanpa pending write domain lain. `commit=False` mempertahankan transaksi milik caller:
tidak ada internal commit dan caller wajib commit/rollback serta memegang guard.
Mode ini tersedia untuk integrasi/test atomik, bukan jalur scheduler produksi yang
membatasi transaksi per batch. Return counter agregasi menghitung bucket yang disentuh
pada run tersebut, bukan jumlah bucket baru sepanjang umur database.

## Penerapan

Tidak ada migrasi baru; gunakan schema head yang sudah mempunyai source fingerprint
retention. Rebuild backend/scheduler dengan versi yang sama:

```sh
docker compose up -d --build backend scheduler
```

Restart terkoordinasi agar tidak meninggalkan cleanup versi lama yang masih memakai
transaksi besar. Worker notifikasi dan frontend tidak memerlukan perubahan IMP-009.
Benchmark hanya boleh dijalankan pada fixture kosong bernama `*_retention_fixture`
dengan `APP_ENV_FILE=''` dan DATABASE_URL eksplisit, melalui
`python -m scripts.benchmark_retention`. Jangan memakai database operasional.
