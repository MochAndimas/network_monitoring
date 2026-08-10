# Deploy Network Monitoring di Synology NAS dengan MikroTik dan cPanel DNS

Dokumen ini menjelaskan deployment Network Monitoring di Synology NAS agar perangkat kantor tetap dimonitor dari jaringan lokal, sementara dashboard dapat diakses aman melalui HTTPS dari luar kantor.

## Arsitektur

```text
Browser
  |
  | https://monitor.domainkamu.com
  v
DNS cPanel
  |
  v
IP publik kantor
  |
  v
MikroTik (port-forward TCP 80 dan 443)
  |
  v
Synology NAS (Reverse Proxy + Let's Encrypt)
  |
  v
Dashboard container (127.0.0.1:8501)

Synology NAS --> perangkat LAN: VoIP, switch, printer, router, NVR, dan lain-lain
```

NAS menjalankan monitoring dari dalam LAN, sehingga dapat memeriksa IP private seperti `192.168.x.x`. Reverse proxy hanya digunakan untuk akses dashboard dari luar kantor.

> Jangan membuka MySQL (`3306`), backend API (`8000`), atau dashboard container (`8501`) langsung ke internet.

## Prasyarat

Siapkan nilai berikut sebelum memulai.

| Item | Contoh | Catatan |
| --- | --- | --- |
| Subdomain dashboard | `monitor.domainkamu.com` | Dibuat melalui DNS di cPanel |
| IP lokal NAS | `192.168.88.10` | Harus statis atau DHCP reservation |
| Interface WAN MikroTik | `ether1-WAN` | Bisa berbeda di tiap router |
| Folder project NAS | `/volume1/docker/network-monitoring` | Sesuaikan volume NAS |
| IP publik kantor | `x.x.x.x` | Harus dapat diakses dari internet |

### Periksa IP publik dan CGNAT

Bandingkan IP pada interface WAN MikroTik dengan IP yang terlihat pada situs pemeriksa IP publik.

Jika IP WAN berada dalam rentang berikut, port-forward dari internet biasanya tidak dapat digunakan:

- `10.0.0.0/8`
- `172.16.0.0/12`
- `192.168.0.0/16`
- `100.64.0.0/10` (CGNAT)

Jika menggunakan CGNAT, gunakan Tailscale/Cloudflare Tunnel atau minta IP publik ke ISP.

## Bagian 1 — Setup Synology NAS

### 1. Install Container Manager

1. Login ke DSM Synology.
2. Buka **Package Center**.
3. Cari **Container Manager**.
4. Klik **Install**.

### 2. Tetapkan IP NAS

Sebaiknya atur DHCP reservation di MikroTik agar NAS selalu memperoleh IP yang sama, misalnya `192.168.88.10`.

Jangan bergantung pada IP DHCP dinamis karena rule MikroTik reverse proxy akan menunjuk ke IP NAS ini.

### 3. Buat folder project

Di File Station, buat folder:

```text
/volume1/docker/network-monitoring
```

Salin seluruh project ke folder tersebut, termasuk file `.env`. Jangan menyimpan `.env` di repository Git karena berisi secret.

### 4. Isi konfigurasi `.env`

Isi semua secret production yang diwajibkan oleh project, termasuk:

- `MYSQL_PASSWORD`
- `MYSQL_ROOT_PASSWORD`
- `AUTH_PASSWORD_SECRET`
- `AUTH_JWT_SECRET`
- `BOOTSTRAP_ADMIN_PASSWORD`
- `CORS_ORIGINS`
- `TRUSTED_HOSTS`
- `DASHBOARD_PUBLIC_API_URL`
- `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID`, bila Telegram digunakan

Gunakan password panjang dan unik. Jangan memakai password NAS sebagai password database atau aplikasi.

### 5. Jalankan project

Melalui Container Manager:

1. Buka **Container Manager** → **Project**.
2. Klik **Create**.
3. Pilih folder project dan file `docker-compose.yml`.
4. Jalankan project.

Alternatif melalui SSH NAS:

```sh
cd /volume1/docker/network-monitoring
docker compose up -d --build
```

Pastikan container berikut berjalan:

- `mysql`
- `backend`
- `scheduler`
- `dashboard`

### 6. Pertahankan dashboard di localhost

Untuk setup reverse proxy, pertahankan pemetaan port berikut pada service dashboard:

```yaml
ports:
  - "127.0.0.1:8501:8501"
```

Dengan ini, dashboard tidak terbuka langsung ke LAN atau internet. Synology Reverse Proxy yang akan mengakses `localhost:8501` dari NAS.

## Bagian 2 — Setup DNS di cPanel

1. Login ke cPanel.
2. Buka **Domains** → **Zone Editor**.
3. Klik **Manage** pada domain yang digunakan.
4. Klik **Add Record** → pilih **A record**.
5. Isi nilai berikut:

| Field | Nilai |
| --- | --- |
| Name | `monitor` |
| Type | `A` |
| Address | IP publik kantor |
| TTL | `300` atau `600` |

Contoh hasil:

```text
monitor.domainkamu.com -> 203.0.113.10
```

Tunggu DNS selesai propagasi sebelum meminta sertifikat Let's Encrypt.

Referensi: [cPanel Zone Editor](https://docs.cpanel.net/cpanel/domains/zone-editor/)

## Bagian 3 — Setup port-forward di MikroTik

> Ganti `192.168.88.10` dengan IP lokal NAS Anda. Jangan menyalin command ini tanpa menyesuaikan interface dan IP.

### Opsi A: WinBox atau WebFig

1. Buka **IP** → **Firewall** → tab **NAT**.
2. Klik tombol **+** untuk membuat rule baru.
3. Buat rule HTTP berikut.

| Field | Nilai |
| --- | --- |
| Chain | `dstnat` |
| Protocol | `tcp` |
| Dst. Port | `80` |
| In. Interface List | `WAN` |
| Action | `dst-nat` |
| To Addresses | `192.168.88.10` |
| To Ports | `80` |

4. Buat rule HTTPS berikut.

| Field | Nilai |
| --- | --- |
| Chain | `dstnat` |
| Protocol | `tcp` |
| Dst. Port | `443` |
| In. Interface List | `WAN` |
| Action | `dst-nat` |
| To Addresses | `192.168.88.10` |
| To Ports | `443` |

### Opsi B: Command RouterOS

```rsc
/ip firewall nat
add chain=dstnat in-interface-list=WAN protocol=tcp dst-port=80 \
    action=dst-nat to-addresses=192.168.88.10 to-ports=80 \
    comment="Synology Let's Encrypt HTTP"

add chain=dstnat in-interface-list=WAN protocol=tcp dst-port=443 \
    action=dst-nat to-addresses=192.168.88.10 to-ports=443 \
    comment="Network Monitoring HTTPS"
```

Jika firewall filter MikroTik memiliki rule drop dari WAN, pastikan ada rule accept untuk koneksi `dstnat` sebelum rule drop tersebut.

```rsc
/ip firewall filter
add chain=forward action=accept connection-nat-state=dstnat \
    protocol=tcp dst-address=192.168.88.10 dst-port=80,443 \
    comment="Allow HTTPS and Let's Encrypt to NAS"
```

Jangan menambahkan forwarding untuk port `3306`, `8000`, atau `8501`.

Referensi: [MikroTik port forwarding](https://help.mikrotik.com/docs/spaces/RKB/pages/154042388/Port%2Bforwarding)

## Bagian 4 — Sertifikat HTTPS Let's Encrypt di Synology

1. Buka **Control Panel** → **Security** → **Certificate**.
2. Klik **Add**.
3. Pilih **Get a certificate from Let's Encrypt**.
4. Isi:

| Field | Nilai |
| --- | --- |
| Domain name | `monitor.domainkamu.com` |
| Email | Email administrator |
| Subject Alternative Name | Kosong, kecuali ada domain tambahan |

5. Klik **Apply**.

Let's Encrypt membutuhkan domain mengarah ke IP publik yang benar dan port `80` dapat diakses dari internet untuk validasi serta renewal otomatis.

Referensi: [Synology Certificate](https://kb.synology.com/en-us/DSM/help/DSM/AdminCenter/connection_certificate)

## Bagian 5 — Reverse Proxy di Synology

1. Buka **Control Panel** → **Login Portal** → **Advanced**.
2. Pada bagian **Reverse Proxy**, klik **Create**.
3. Isi konfigurasi berikut:

| Field | Nilai |
| --- | --- |
| Name | `Network Monitoring` |
| Source protocol | `HTTPS` |
| Source hostname | `monitor.domainkamu.com` |
| Source port | `443` |
| Destination protocol | `HTTP` |
| Destination hostname | `localhost` |
| Destination port | `8501` |

4. Simpan rule.
5. Kembali ke **Control Panel** → **Security** → **Certificate**.
6. Klik **Settings/Configure**, lalu pasangkan sertifikat `monitor.domainkamu.com` untuk layanan/rule reverse proxy tersebut.

Aktifkan HSTS hanya setelah dashboard dan HTTPS sudah terbukti normal.

Synology juga dapat membuat access-control profile untuk membatasi akses berdasarkan source IP/CIDR.

Referensi: [Synology Reverse Proxy](https://kb.synology.com/en-global/DSM/help/DSM/AdminCenter/system_login_portal_advanced?version=7)

## Bagian 6 — Hardening wajib

Selesaikan checklist berikut sebelum membagikan URL dashboard.

- [ ] Update DSM dan Container Manager.
- [ ] Gunakan akun admin NAS unik dan aktifkan 2FA.
- [ ] Nonaktifkan akun `admin` bawaan DSM bila memungkinkan.
- [ ] Batasi port DSM (`5001`) hanya untuk LAN, VPN, atau IP admin tertentu.
- [ ] Aktifkan firewall NAS.
- [ ] Hanya forward port `80` dan `443` dari MikroTik ke NAS.
- [ ] Jangan expose MySQL, backend API, atau dashboard container secara langsung.
- [ ] Gunakan password aplikasi yang kuat.
- [ ] Backup volume MySQL secara berkala.
- [ ] Periksa renewal sertifikat Let's Encrypt setelah beberapa hari.

Jika hanya sedikit user yang mengakses dashboard, pertimbangkan access-control profile Synology atau akses melalui VPN/Tailscale sebagai lapisan tambahan.

## Bagian 7 — Uji dari luar kantor

Gunakan data seluler, bukan Wi-Fi kantor.

1. Buka `https://monitor.domainkamu.com`.
2. Pastikan browser menunjukkan sertifikat HTTPS valid.
3. Login ke dashboard.
4. Pastikan data monitoring terus masuk.
5. Pastikan alert Telegram tetap berfungsi.

## Troubleshooting

### Domain tidak bisa dibuka

Periksa:

1. A record cPanel mengarah ke IP publik kantor.
2. WAN MikroTik bukan CGNAT.
3. NAT rule TCP 80 dan 443 aktif.
4. Firewall filter MikroTik mengizinkan koneksi `dstnat` ke NAS.
5. Firewall NAS tidak memblokir port 80/443.

### Let's Encrypt gagal

Periksa:

1. Domain sudah resolve ke IP publik yang benar.
2. Port 80 diarahkan ke NAS.
3. Port 80 tidak digunakan oleh perangkat lain.
4. NAS dapat mengakses internet dan waktu sistem benar.

### HTTPS berhasil, tetapi dashboard error

Periksa:

1. Container dashboard sedang running.
2. Dashboard bisa diakses dari NAS melalui `http://127.0.0.1:8501`.
3. Reverse proxy tujuan benar: `HTTP`, `localhost`, port `8501`.
4. Environment production dashboard sudah benar.

### Monitoring perangkat LAN tidak berjalan

Periksa:

1. NAS berada di subnet yang dapat menjangkau perangkat.
2. NAS dapat mengakses gateway dan device LAN.
3. IP device pada aplikasi benar.
4. Perangkat tidak memblokir metode monitor yang digunakan, misalnya ICMP ping atau SNMP.

## Setelah deployment

- Cek log container setelah upgrade.
- Backup MySQL sebelum update besar.
- Review akun dashboard secara berkala.
- Uji akses eksternal dan renewal sertifikat tiap beberapa bulan.
- Bila menambah cabang, gunakan VPN site-to-site atau pasang monitor lokal di cabang tersebut.
