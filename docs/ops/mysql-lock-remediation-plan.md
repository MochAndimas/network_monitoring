# Rencana perbaikan lock MySQL Network Monitoring

Tujuannya adalah membuat monitoring, pengolahan bandwidth, dan retention berjalan bersamaan di NAS. Job harus selesai sesuai jadwal, metrik tetap mutakhir, dan backlog sementara harus bisa habis setelah beban turun. Perbaikan harus menjaga konsistensi data saat ada transaksi paralel, retry, atau proses yang berhenti di tengah pekerjaan.

## Progres implementasi

- [x] Scheduler mencoba ulang penyimpanan metrik sekali setelah rollback penuh untuk MySQL 1205 atau 1213. Retry memakai payload koleksi yang sama dan berlaku sebelum fase commit. Kegagalan koneksi dan hasil commit yang tidak pasti tidak diulang otomatis.
- [x] Retention operasional mengambil lock satu perangkat, lalu memakai pembacaan snapshot baru untuk memilih ID metrik dan memvalidasi checkpoint tanpa mengunci rentang metrik yang dipindai. Delete tetap memvalidasi kelayakan sumber saat mengeksekusi penghapusan. Jalur transaksi milik pemanggil tetap memakai locking read.
- [x] Tambah durasi fase pencarian kandidat, lock perangkat, validasi checkpoint, pencarian sumber, agregasi, delete, dan penyelesaian batch retention.
- [x] Jika operasi dan pelepasan advisory lock sama-sama gagal, log mencatat kegagalan pelepasan dan scheduler menerima error operasi asli. Jika hanya pelepasan yang gagal, error tersebut tetap diteruskan.
- [x] Regresi lokal untuk scheduler, retention, bandwidth, dan observability menghasilkan 229 lulus dan 3 dilewati.
- [x] Suite integrasi MySQL 8.4 pada database sementara yang dimigrasikan dari awal menghasilkan 22 lulus. Cakupannya termasuk penulis metrik paralel, retention yang menunggu commit penulis, dan contention advisory lock scheduler.
- [x] Retry terkonfirmasi aktif di scheduler NAS melalui log `metric_write_retry` pada 11 November 2026.
- [x] Verifikasi hasil retry MikroTik di NAS. Dua run pulih setelah retry dan dua run masih gagal dengan 1205.
- [ ] Verifikasi setidaknya satu run retention di NAS dan ukur ulang contention MikroTik saat job saling overlap.
- [x] Tambah profil `metric_insert_profile` di jalur flush metrik. Log mencatat ukuran batch, durasi, dan panggilan cursor INSERT yang berhasil pada koneksi batch. Jumlah statement yang dikirim driver untuk satu `executemany` perlu diverifikasi di MySQL jika jalur itu muncul.
- [x] Verifikasi profil pada dua batch terpisah di regresi lokal. Suite terkait menghasilkan 38 lulus.
- [x] Ambil profil batch MikroTik di NAS. Sampel mengonfirmasi 274 panggilan `execute` untuk 274 metrik.
- [x] Uji konsep bulk insert dengan token korelasi unik di MySQL lokal 8.4.11. Batch 274 baris memerlukan 97,52 ms dengan insert satu per satu dan 14,62 ms dengan satu panggilan `executemany` serta satu query pemetaan ID. Kedua pengukuran mencakup penulisan snapshot uji dan commit. Dua penulis paralel pada perangkat berbeda, timestamp sama, referensi snapshot, dan rollback lulus pada skema uji.
- [x] Validasi prototipe melalui `MetricRepository.create_metrics()` pada MySQL lokal dengan skema Alembic lengkap dan kolom token eksperimental. Lima tes terarah lulus, mencakup dua penulis pada perangkat yang sama, penulis perangkat lain, tie-break ID, uptime streak, rollback dan retry, serta retention yang menunggu commit penulis.
- [x] Benchmark 274 metrik dengan 100.000 baris histori sintetis. Median lima run turun dari 111,67 ms menjadi 36,71 ms, termasuk snapshot dan commit. Panggilan INSERT raw metrics turun dari 274 menjadi 1, dengan satu SELECT tambahan untuk memetakan token ke ID.
- [x] Implementasikan bulk insert MySQL dengan batch maksimal 500, pemetaan ID berdasarkan token unik, dan snapshot dalam transaksi yang sama. Suite MySQL lulus 22 tes, termasuk uji presisi timestamp dalam satu detik dan penulis paralel.
- [x] Uji migrasi `20261112_0034` pada 100.000 baris lama. Upgrade lokal butuh 1,58 detik termasuk startup Alembic. Jumlah baris tetap 100.000 setelah upgrade dan downgrade, dan semua token historis tetap NULL setelah upgrade. Pemeriksaan drift skema MySQL juga lulus.
- [ ] Ukur durasi DDL dan pertumbuhan indeks pada data mendekati ukuran NAS. Sampel 100.000 baris tidak mengukur dampak DDL pada penulis aktif atau ukuran tabel produksi.
- [x] Deploy bulk insert di NAS dan verifikasi satu run MikroTik sukses dengan profil batch aktif.
- [ ] Ulangi pengukuran saat job overlap dan cek fase setelah commit jika durasi total masih tinggi. Identifikasi blocker perangkat 1 jika timeout kembali muncul.
- [x] Pisahkan evaluasi alert dari kolektor terjadwal. Kolektor selesai setelah commit metrik dan pelepasan lock penulisan. Job `alert_evaluation` di scheduler central tetap membaca metrik yang sudah commit dan memakai lock alert. Site agent tetap mengirim metrik ke database bersama.
- [x] Verifikasi 65 tes regresi lokal dan 22 tes integrasi MySQL 8.4. Tes lock aktual membuktikan kolektor bisa commit saat lock alert dipegang, evaluator melewati siklus yang sibuk, dan evaluasi berikutnya bisa commit setelah lock bebas.
- [x] Verifikasi pemisahan di NAS pada 12 November 2026 sekitar 13.43–13.56 WIB. Tiga belas run MikroTik sukses dalam 14,75–53,16 detik. Selang dari akhir commit ke log sukses turun menjadi 1,17–12,21 detik. Tujuh run alert terpisah sukses dalam 82,50–134,27 detik.
- [ ] Ukur freshness alert dari metrik pemicu sampai alert tercatat dan periksa antrean notifikasi saat evaluator sibuk. Fase evaluasi masih berlangsung 71,33–123,75 detik pada sampel NAS.

### Sampel NAS setelah deploy

Pada 11 November 2026, sekitar 13.55–14.01 WIB, `internet_checks` mencatat 11 sukses dan lock perangkat didapat dalam 1,38–13,21 ms pada sampel. `device_checks`, `server_checks`, `alert_evaluation`, dan satu run `mikrotik_checks` juga selesai.

Run MikroTik berikutnya sempat timeout setelah 50,83 detik. Retry memperoleh lock setelah 25,78 detik, dan sampel berakhir sebelum hasil akhir job itu terlihat. Insert MikroTik pada run sebelumnya masih butuh 129,13 detik. Belum ada run retention yang terlihat di sampel ini.

Sampel lanjutan hingga 14.22 WIB mencatat sembilan run MikroTik sukses dan dua gagal. Dari empat retry, dua berakhir sukses dan dua tetap timeout saat mengambil lock perangkat 2 dan 41. Lima run terakhir sukses, dengan durasi turun dari sekitar 110 detik ke 62 detik. Filter log masih belum menampilkan hasil retention.

Pada 12 November 2026, sampel sekitar 09.09–09.30 WIB mencatat 10 batch MikroTik sukses, masing-masing 270–274 metrik, dengan durasi koleksi sampai pencatatan run 30,91–123,60 detik. Pada delapan run dengan log fase, pengambilan lock memerlukan 1,84–53,56 detik, insert/flush 21,09–84,51 detik, dan commit 2,34–12,37 detik. Ukuran batch hampir tetap walau durasi berubah jauh. Snapshot global mencatat 498.301 eksekusi INSERT dan 498.280 baris terdampak, mendekati satu baris per eksekusi secara agregat. Jumlah statement khusus MikroTik dan penyebab variasi durasi belum terukur.

Profil MikroTik pada 12 November 2026 pukul 09.50 WIB mencatat 274 metrik, 274 panggilan `execute`, dan 0 `executemany`. Insert/flush memerlukan 95,89 detik setelah fase pengambilan lock yang berlangsung 29,97 detik. Commit selesai dalam 1,20 detik. Gunakan angka ini sebagai pembanding awal. Satu sampel belum memisahkan biaya round trip dari waktu eksekusi dan wait di MySQL.

Setelah rollout pada 12 November 2026 sekitar 12.38–12.40 WIB, batch MikroTik 274 metrik memakai satu panggilan `executemany`. Waktu profil insert turun dari 95,89 ke 11,67 detik pada perbandingan dua sampel. Fase pengambilan lock turun dari 29,97 ke 10,27 detik, sementara commit naik dari 1,20 ke 8,60 detik. Job sukses dalam 131,21 detik. Sekitar 98 detik berlalu antara log commit dan log sukses. Periksa fase evaluasi alert pada run yang sama sebelum mengaitkan selang itu dengan satu operasi.

Log lanjutan mengonfirmasi fase evaluasi alert setelah commit metrik memakai 87,87 detik pada run pertama dan 46,93 detik pada run berikutnya. Empat batch bulk 274 metrik memerlukan 11,67–40,70 detik per insert/flush. Satu percobaan lock masih timeout 1205, lalu retry berhasil menyimpan dan commit metrik. Hasil akhir job tersebut belum terlihat di sampel. Prioritas selanjutnya adalah memisahkan evaluasi alert terjadwal dari durasi job kolektor, dengan verifikasi freshness alert dan penanganan lock. Contention pada perangkat tetap perlu dipantau secara terpisah.

### Deploy tahap ini ke NAS

Untuk perubahan pemisahan alert pada NAS yang sudah memakai skema `20261112_0034`, build dan recreate scheduler. Jika cleanup sedang berjalan atau mendekati jadwal, tunggu hasilnya karena recreate mengulang jadwal interval. Jika ada scheduler site agent lain, rollout setelah scheduler central sehat.

```bash
sudo docker compose build scheduler &&
sudo docker compose up -d --no-deps scheduler
```

Setelah beberapa siklus, ambil log kedua job dari scheduler central.

```bash
sudo docker compose logs --since=20m scheduler 2>&1 |
  grep -E '"job_name": "(mikrotik_checks|alert_evaluation)"' |
  grep -E 'phase=(commit_metrics|evaluate)|scheduler_lock_skipped|scheduler_job_(completed|failed)' |
  tail -n 40
```

Untuk rollout bulk insert, jalankan migrasi sebelum recreate scheduler. Gunakan folder project NAS dan konfigurasi produksi yang sama dengan migrasi sebelumnya. Jadwalkan di luar jam sibuk dan tunggu cleanup aktif selesai. MySQL meminta DDL online melalui `LOCK=NONE` dan tetap memerlukan metadata lock.

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.migrate-production.yml --profile ops build migrate &&
sudo docker compose -f docker-compose.yml -f docker-compose.migrate-production.yml --profile ops run --rm migrate &&
sudo docker compose build scheduler &&
sudo docker compose up -d --no-deps scheduler
```

Untuk rollback aplikasi, jalankan image scheduler lama terlebih dahulu. Kolom nullable kompatibel dengan image lama. Downgrade skema hanya setelah semua service yang menggunakan model baru sudah dikembalikan ke versi lama.

Untuk mengambil profil insert setelah deploy, jalankan perintah berikut sesudah beberapa siklus MikroTik.

```bash
sudo docker compose logs --since=20m scheduler 2>&1 |
  grep -F '"job_name": "mikrotik_checks"' |
  grep -E 'metric_insert_profile|metric_device_row_lock|commit_metrics' |
  tail -n 30
```

Setelah source terbaru tersinkron, build dan recreate service scheduler dari folder project NAS. Tunggu run retention selesai jika sedang berlangsung. Recreate mengulang jadwal interval scheduler.

```bash
sudo docker compose build scheduler &&
sudo docker compose up -d --no-deps scheduler
```

Ambil log setelah beberapa siklus monitoring dan satu run retention.

```bash
sudo docker compose logs --since=30m scheduler 2>&1 |
  grep -E 'metric_write_retry|metric_history_insert_flush|metric_device_row_lock|retention_|scheduler_job_(failed|completed)'
```

Jika `internet_checks` kembali timeout, ambil rantai lock perangkat 1 saat wait masih berlangsung. Simpan hasil bersama log fase dan jam pengambilan untuk menentukan transaksi yang perlu dipercepat.

## Temuan produksi

| Temuan | Bukti dan batas kesimpulan |
| --- | --- |
| Internet checks gagal berulang | System Health mencatat 72 kegagalan berturut-turut. Log menunjukkan error 1205 setelah sekitar 50 detik menunggu lock `devices.id=1`. Sampel terbaru belum menangkap pemegang lock untuk ID ini. |
| MikroTik checks bersaing dengan penulis metrik | MySQL menangkap transaksi `INSERT INTO metrics` memegang lock perangkat 2 dan 41. Wait mencapai 45–48 detik pada satu sampel. Log juga mencatat satu timeout MikroTik dan satu insert MikroTik sekitar 139 detik. Query aktif saja belum menunjukkan apakah transaksi itu sedang menunggu resource lain. |
| Penulisan metrik menahan lock lama | Pada `device_checks`, lock didapat sekitar 3 ms, kemudian fase insert/flush berlangsung 77–120 detik. Commit diukur terpisah. Job ini mengecualikan tipe `internet_target`, sehingga perlu bukti langsung untuk mengaitkannya dengan perangkat 1. |
| Retention pernah memblokir perangkat | Sampel sebelumnya menangkap transaksi retention menahan lock di `devices` saat mencari metrik lama dan wait mencapai 47 detik. Patch pencarian kandidat tanpa lock sudah terkonfirmasi ada di container scheduler. Validasi dan pencarian sumber masih berjalan setelah lock perangkat diambil. |
| Retention kehilangan koneksi | Ada tiga kegagalan dengan error 2013 saat `RELEASE_LOCK`. Belum diketahui apakah pekerjaan di dalam job juga gagal. Batch yang sudah commit perlu dibedakan dari transaksi terakhir. |
| Jalur bandwidth juga mengalami contention | Sampel sebelumnya menangkap transaksi flow insert dan inventory/IP history bersaing di `devices`. Perbaikan indeks pencarian segmen sudah terlihat di kedua worker. Jumlah file antrean terakhir sempat turun ke kisaran satu digit. Validasi ulang dengan beban saat ini. |
| Evaluasi alert pernah menambah waktu tunggu | Scheduler sudah memakai percobaan advisory lock nonblocking untuk evaluasi setelah penyimpanan metrik. Query riwayat alert sudah dioptimasi. Verifikasi evaluasi berkala tetap mengejar metrik baru saat percobaan langsung dilewati. |

## P0 — Tangkap pemegang lock dan buat baseline

- [ ] Catat versi image yang berjalan, versi skema, jadwal job, dan jumlah metrik per batch. Cocokkan waktu log container dan MySQL ke zona waktu yang sama.
- [ ] Saat `internet_checks` menunggu, ambil rantai dari `sys.innodb_lock_waits` dan `performance_schema.data_locks`. Rekam primary key yang terkunci, mode lock, umur transaksi, koneksi yang menunggu dan memblokir, serta digest SQL kedua sisi. Ikuti rantai hingga transaksi terakhir, termasuk lintas tabel.
- [ ] Petakan koneksi blocker ke container dan job. Tambahkan korelasi ID koneksi MySQL dengan job atau fase pada log diagnostik jika pemetaan dari IP container dan waktu belum cukup. Pakai digest SQL dan hindari menyimpan kredensial atau nilai payload.
- [ ] Bandingkan jumlah baris, jumlah statement, durasi insert/flush, snapshot, commit, dan lock wait pada batch normal serta batch besar. Cek latensi tulis dan antrean disk saat fase lambat. Throughput disk, jumlah lock, dan satu sampel CPU saja belum cukup untuk menyimpulkan penyebab.
- [ ] Simpan baseline dalam periode representatif yang mencakup overlap scheduler, ingestion kedua site, dan setidaknya satu run retention.

## P1 — Perpendek transaksi penulisan metrik

Kode utama ada di `backend/app/repositories/metrics/writes.py`, `backend/app/services/monitoring_service.py`, dan `backend/app/scheduler/jobs.py`.

- [ ] Ukur SQL yang benar-benar dihasilkan MySQL oleh jalur ORM. Bandingkan dengan strategi insert yang mengurangi round trip pada batch representatif, termasuk dampak terhadap durasi memegang lock.
- [ ] Pilih strategi yang mempertahankan pemetaan ID metrik secara eksplisit dan benar pada insert konkuren. Hindari menebak rentang ID dari `LAST_INSERT_ID()`. Pertahankan aturan latest berdasarkan `checked_at` dan ID saat timestamp sama.
- [ ] Lakukan koleksi perangkat dan persiapan payload sebelum transaksi write. Pertahankan urutan lock yang konsisten. Evaluasi batch terbatas per perangkat atau kelompok perangkat bila transaksi masih terlalu lama.
- [ ] Jika satu run dipecah menjadi beberapa transaksi, definisikan hasil parsial dan perilaku retry. Pastikan raw metric, latest snapshot, dan metadata inventory yang saling bergantung konsisten. Catat sukses job setelah seluruh pekerjaan yang diwajibkan selesai.
- [ ] Terapkan perbaikan spesifik pada jalur yang terbukti memegang lock perangkat 1. Jika blocker adalah retention, selesaikan jalur P1 retention. Jika blocker adalah penulis lain, ukur fase yang memperpanjang transaksinya dan perbaiki di jalur tersebut.
- [ ] Jika menambah retry untuk 1205 atau 1213, rollback transaksi penuh sebelum retry, beri batas percobaan, dan pastikan operasi aman diulang. Catat kegagalan yang habis percobaan di System Health.

## P1 — Kurangi contention retention dan perjelas kegagalan

Kode utama ada di `backend/app/repositories/retention_repository.py`, `backend/app/services/retention_service.py`, dan `backend/app/services/pipeline_control.py`.

- [ ] Ukur pencarian kandidat, pengambilan lock perangkat, pemeriksaan checkpoint, agregasi, delete, dan commit secara terpisah. Ambil `EXPLAIN` dari SQL yang dipakai pada data representatif sebelum menentukan indeks atau mengubah query.
- [ ] Pendekkan pencarian sumber setelah lock perangkat. Evaluasi pemilihan kandidat metrik secara terbatas sebelum lock dan validasi ulang kandidat di transaksi write. Pastikan checkpoint tetap aman bila penulis lain commit di antara kedua fase, termasuk commit terlambat dengan ID lebih kecil.
- [ ] Batasi pekerjaan per transaksi. Jaga checkpoint dan agregat terkait tetap atomik. Hapus raw metrics hanya jika rollup, arsip, dan checkpoint yang diperlukan tersedia, dengan referensi latest metric tetap terlindungi.
- [ ] Pertahankan kontrak pemanggil yang mengelola transaksi sendiri. Uji perilaku snapshot MySQL, restart di tengah batch, retry, dan eksekusi cleanup yang tumpang tindih.
- [ ] Pisahkan pelaporan kegagalan pekerjaan dari kegagalan pelepasan advisory lock. Saat keduanya gagal, simpan error utama beserta error pelepasan. Tangani koneksi yang putus sesuai status kepemilikan lock dan buktikan cleanup berikutnya bisa mengambil lock dan melanjutkan checkpoint.
- [ ] Ukur laju pengurangan backlog retention. Jika batch lebih kecil, pastikan total pekerjaan per jadwal masih mengejar pertumbuhan data.

## P2 — Periksa jalur bandwidth dan alert di bawah beban yang sama

- [ ] Ukur contention antara flow worker, inventory, reconciliation, dan penulis metrik per router. Fokus pada transaksi yang terbukti memblokir `devices`, `bandwidth_client_ip_history`, atau `bandwidth_flows`. Rekam durasi lock, insert, commit, dan ukuran batch.
- [ ] Verifikasi pencarian segmen memakai indeks pending pada MySQL. Pertahankan urutan lock yang konsisten dan batasi reconciliation per transaksi jika terbukti menahan lock lama.
- [ ] Jaga idempotensi ingest berdasarkan stream, segmen, dan offset. Pertahankan urutan commit database lalu acknowledgement spool. Uji restart di tengah batch, termasuk duplikasi, segmen yang diproses ulang, dan sinkronisasi agregat harian.
- [ ] Pantau laju flow diterima, umur file antrean tertua, tren file `*.ready`, restart collector, dan error database per site. Gunakan umur dan laju antrean untuk menilai keterlambatan selama trafik aktif.
- [ ] Uji evaluasi alert berkala saat lock evaluasi langsung sibuk. Pastikan alert dan notifikasi yang sudah diproses tetap konsisten saat retry, dan umur antrean tidak tumbuh terus.
- [ ] Pastikan System Health menampilkan keberhasilan terakhir, durasi, dan kegagalan aktif secara akurat. Counter kegagalan harus pulih mengikuti keberhasilan job yang sebenarnya.

## Standar implementasi dan pengujian

- [ ] Tempatkan SQL dan keputusan akses data di repository, batas transaksi di service atau runner yang memilikinya, dan penjadwalan di scheduler. Pakai kembali mekanisme batch, checkpoint, dan timing yang sudah ada.
- [ ] Pakai query dan transaksi dengan batas ukuran yang jelas. Hindari satu lock global untuk seluruh pekerjaan serta kerja per baris yang menambah round trip tanpa kebutuhan.
- [ ] Ukur setiap perubahan performa sebelum dan sesudah. Simpan ukuran batch, jumlah statement, durasi transaksi, dan hasil uji beban agar tuning berikutnya bisa ditelusuri.
- [ ] Jalankan regresi repository, scheduler, retention, dan bandwidth sesuai komponen yang berubah. Tambahkan tes spesifik untuk konflik writer, rollback/retry, pemetaan ID, dan resume checkpoint bila jalur itu diubah.
- [ ] Jalankan uji integrasi pada MySQL 8.4 dengan beberapa koneksi paralel dan volume data representatif. Gunakan SQLite untuk regresi fungsional yang sesuai. Verifikasi lock dan query plan dengan MySQL.
- [ ] Siapkan rollback per perubahan. Untuk migrasi indeks atau skema yang terbukti perlu, cek biaya DDL dan kompatibilitas aplikasi sebelum deploy. Terapkan perubahan satu tahap dan ukur hasilnya sebelum lanjut.

## Kriteria selesai di NAS

- [ ] `internet_checks`, `mikrotik_checks`, `device_checks`, dan `server_checks` rutin mencatat sukses, tanpa error 1205/1213 berulang dan tanpa heartbeat stale berkepanjangan saat trafik normal.
- [ ] Durasi lock dan persentil durasi job turun dari baseline. Metrik terbaru tetap diperbarui sesuai interval masing-masing job selama ada overlap.
- [ ] Setidaknya satu run retention produksi selesai, checkpoint bergerak, dan run berikutnya dapat melanjutkan. Validasi restart dan retry pada pengujian terkontrol.
- [ ] Flow HO dan RO terus masuk, umur antrean turun kembali setelah lonjakan, dan jumlah restart collector stabil. Cocokkan hasil agregasi sampel dengan flow sumber.
- [ ] Alert terproses dan antrean notifikasi normal selama pengujian bersama. System Health sesuai dengan log dan status aktual.
- [ ] Catat periode pengamatan, versi yang dideploy, perbandingan sebelum/sesudah, dan bukti tiap kriteria. Tutup pekerjaan setelah melewati periode trafik representatif yang mencakup overlap job dan jadwal cleanup.
