# Operational Runbook

Runbook ini menjadi SOP operasional minimum untuk environment production.

## 1. Backup Database

Target RPO:
- Harian: maksimal kehilangan data 24 jam.
- Rekomendasi: backup penuh harian + backup tambahan sebelum perubahan besar (migration, upgrade versi, rotasi secret).

Perintah contoh (dari host yang bisa akses MySQL):

```bash
mysqldump \
  --single-transaction \
  --quick \
  --routines \
  --triggers \
  -h 127.0.0.1 \
  -u network_monitoring \
  -p network_monitoring > backup/network_monitoring_YYYYMMDD_HHMM.sql
```

Checklist backup:
1. Pastikan file backup berhasil dibuat dan ukuran tidak nol.
2. Simpan checksum (`sha256sum`) untuk integritas.
3. Upload ke storage terpisah (off-host/off-site) dengan retention policy.
4. Catat hasil di log operasional (waktu, operator, ukuran file, checksum, lokasi upload).

## 2. Restore Database

Target RTO:
- Service recovery target awal: <= 120 menit.

Langkah restore:
1. Isolasi akses write ke backend/scheduler (stop service write path jika perlu).
2. Provision database target restore.
3. Restore dump:

```bash
mysql -h 127.0.0.1 -u network_monitoring -p network_monitoring < backup/network_monitoring_YYYYMMDD_HHMM.sql
```

4. Jalankan migration:

```bash
alembic upgrade head
```

5. Validasi:
1. `GET /health/ready` = 200.
2. `GET /health/dependencies` = healthy.
3. Login dashboard berhasil.
4. `POST /system/run-cycle` berhasil (tidak stuck lock/deadlock).
6. Dokumentasikan waktu start/finish untuk pengukuran RTO aktual.

## 3. DR Drill (Quarterly)

Frekuensi:
- Minimal 1 kali per kuartal.

Skenario drill minimum:
1. Simulasi kehilangan instance database.
2. Restore dari backup terakhir.
3. Naikkan backend + scheduler + dashboard.
4. Jalankan smoke test inti.

Exit criteria:
1. RTO aktual <= target.
2. Data pasca restore lolos sampling konsistensi (devices/metrics/auth session).
3. Semua action item dicatat dan diprioritaskan.

Dokumen evidence drill:
- Tanggal/jam drill.
- Operator yang bertugas.
- Backup source yang dipakai.
- RTO aktual.
- Masalah yang ditemukan.
- Rencana perbaikan + owner + due date.

## 4. Incident Response SOP

Severity baseline:
- Sev-1: layanan monitoring core down total / blind monitoring.
- Sev-2: degradasi berat fungsi inti (auth, scheduler, DB latency tinggi, data freshness rusak).
- Sev-3: degradasi minor, ada workaround.

Flow respon:
1. Deteksi: alert dari observability/health/ops report.
2. Triage: tentukan severity dan blast radius.
3. Mitigasi awal: hentikan eskalasi dampak (containment).
4. Recovery: pulihkan layanan.
5. Verifikasi: pastikan KPI health kembali normal.
6. Postmortem: dokumentasi akar masalah dan preventive action.

SLA respon (target):
- Sev-1: ack <= 5 menit, mitigasi awal <= 30 menit.
- Sev-2: ack <= 10 menit, mitigasi awal <= 60 menit.
- Sev-3: ack <= 30 menit, mitigasi awal <= 1 hari kerja.

## 5. SLO Alerting Actionability

### SLO Target (baseline)

- API availability bulanan: >= 99.5%
- Scheduler cycle success rate harian: >= 99.0%
- Freshness metric utama (latest snapshot): <= 5 menit lag untuk 99% sampel
- Error rate endpoint kritis (`/auth/*`, `/dashboard/*`, `/metrics/*`): < 1% rolling 15 menit

### MTTA/MTTR Target

- MTTA:
1. Sev-1 <= 5 menit
2. Sev-2 <= 10 menit
- MTTR:
1. Sev-1 <= 120 menit
2. Sev-2 <= 240 menit

### Notification dan Escalation Chain

Urutan notifikasi:
1. On-call engineer (primary)
2. On-call backup
3. Incident commander (jika Sev-1/Sev-2 > 15 menit tanpa mitigasi)
4. Engineering lead / ops lead

Escalation policy:
1. Jika alert critical tidak di-ack dalam 5 menit -> eskalasi ke backup.
2. Jika belum ada mitigasi 15 menit -> eskalasi ke incident commander.
3. Jika > 30 menit tanpa stabilisasi -> eskalasi ke lead + komunikasi stakeholder.

### Template Data Yang Harus Ada di Tiap Alert

Setiap alert operasional wajib memuat:
1. `what`: ringkasan masalah.
2. `where`: service/endpoint/job terdampak.
3. `since`: kapan mulai terjadi.
4. `impact`: dampak ke user/ops.
5. `runbook`: pointer ke langkah SOP yang relevan.
6. `owner`: siapa yang harus ack.

## 6. Operational Checklist Harian

1. Cek `GET /health/ready` dan `GET /health/dependencies`.
2. Cek `/observability/summary` untuk error trend dan scheduler status.
3. Verifikasi job `retention_cleanup` sukses minimal sekali per 24 jam.
4. Verifikasi backup terbaru valid.
5. Review alert aktif stale (>24 jam) untuk action follow-up.
