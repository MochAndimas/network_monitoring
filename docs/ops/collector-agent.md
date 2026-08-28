# Collector Agent Per Site

Agent membaca device dengan `site` yang persis sama dengan `COLLECTOR_AGENT_SITE`, menjalankan ping/SNMP dari LAN site tersebut, lalu menulis metric ke MySQL pusat melalui VPN.

## Topologi aman

`agent di site -> VPN private -> MySQL pusat`

Tidak ada port API MikroTik, SNMP, printer, NAS, atau dashboard yang dibuka ke internet publik. Batasi MySQL/firewall VPN agar hanya alamat agent yang dapat mengakses database.

## Aktivasi

1. Pastikan semua device branch memiliki nilai `site` konsisten, misalnya `Kantor Cabang`.
2. Pada scheduler pusat set `COLLECTOR_AGENT_SITES=Kantor Cabang` agar pusat tidak mem-poll site tersebut.
3. Pada server branch, set `DATABASE_URL` menuju MySQL pusat melalui alamat VPN dan `COLLECTOR_AGENT_SITE=Kantor Cabang`.
4. Jalankan `docker compose -f docker-compose.collector-agent.example.yml up -d --build`.
5. Cek System Health: `device_checks` harus fresh dan metric branch berubah setiap interval.

## Rollback

Stop agent, hapus site dari `COLLECTOR_AGENT_SITES` di pusat, lalu restart scheduler pusat. Jangan menjalankan central polling dan agent untuk site yang sama karena metric akan duplikat.
