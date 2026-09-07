# CGG Trading Guard

Implementasi kerja dari `CGG-Trading-Guard-Spesifikasi-Sistem.md`. Sistem
penasihat (bukan prediktor, bukan auto-trader) untuk dua keputusan: harga
beli maksimum ke petani, dan jual-vs-tahan untuk lot yang sudah dibeli.

## Menjalankan secara lokal

```bash
pip install -r requirements.txt

# Satu siklus penuh (ambil ONI + cuaca, hitung Buy/Sell Guard, susun brief)
python run_once.py

# Dashboard interaktif
streamlit run dashboard/app.py

# Mode produksi: proses latar belakang yang jalan sesuai jadwal
# (06:00 pagi, 17:00 sore, tgl 8 tiap bulan) — biarkan terminal ini menyala,
# atau daftarkan sebagai Windows Task/Service untuk jalan terus-menerus.
python -m src.scheduler
```

## Menjalankan di Streamlit Community Cloud

1. Push/upload repo ini ke GitHub (branch `main`).
2. [share.streamlit.io](https://share.streamlit.io) → Sign in with GitHub → **New app**.
3. Pilih repo ini, branch `main`, **main file path: `dashboard/app.py`**.
4. Deploy. `requirements.txt` di root sudah cukup — tidak perlu `packages.txt` (murni Python + SQLite).

### ⚠️ Batasan penting mode cloud (baca sebelum dianggap "otomatis penuh")

Streamlit Community Cloud **hanya menjalankan `dashboard/app.py`** — ia **tidak**
menjalankan `src/scheduler.py` di latar belakang. Dua konsekuensi:

- **Data tidak otomatis mengalir jam 06:00/17:00** seperti yang dibayangkan
  spesifikasi bagian 7.5. Untuk menutup ini, dashboard punya **auto-bootstrap**:
  begitu seseorang membuka halaman, ia otomatis menarik ONI & cuaca hari ini
  (kalau belum ada) dan menghitung ulang Buy Guard (kalau harga hari ini sudah
  diisi) — jadi selama seseorang membuka dashboard tiap pagi, datanya tetap segar
  tanpa proses cron terpisah. Harga tetap **sengaja tidak** di-auto-isi (lihat
  spesifikasi 3.1 — Layer 3 harus manual).
- **Penyimpanan tidak permanen.** Container Streamlit Cloud bisa tidur dan
  bangun dengan storage bersih kapan saja — `data/cgg.db` bisa ter-reset ke
  kosong. Cocok untuk **demo, uji coba, dan berbagi ke tim**; belum cocok
  untuk operasional harian yang datanya harus terus terkumpul (band skenario
  di Sell Guard butuh histori harga yang menumpuk). Untuk pemakaian produksi
  sungguhan, ikuti rekomendasi asli spesifikasi: satu VPS kecil atau laptop
  kantor yang selalu menyala, dengan `python -m src.scheduler` jalan terus.

## Mengirim Daily Brief ke email (opsional)

Modul `src/notify/email_sender.py` bisa mengirim brief lewat email SMTP,
**aktif hanya jika Anda mengisi kredensialnya sendiri** lewat Streamlit
Secrets — Claude/AI tidak pernah memegang kredensial ini:

1. Di Streamlit Cloud: buka app → **⋮ → Settings → Secrets**.
2. Tempel:
   ```toml
   [smtp]
   host = "smtp.gmail.com"
   port = 465
   user = "akun-pengirim@gmail.com"
   password = "app-password-16-digit"
   to = "koordinator@cgg.co.id"
   ```
   (Gmail: pakai [App Password](https://myaccount.google.com/apppasswords), bukan password akun biasa.)
3. Simpan → tombol **"Kirim brief ini ke email"** di tab Data Pasar & Iklim akan aktif.

Untuk lokal, isi variabel environment `SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/SMTP_TO`
sebagai gantinya, atau buat `.streamlit/secrets.toml` (sudah di-`.gitignore`, jangan pernah di-commit).

## Yang sudah benar-benar berfungsi

- **Database SQLite** — skema lengkap sesuai spesifikasi bagian 6.
- **Ingest iklim (ONI/NOAA)** dan **cuaca (Open-Meteo)** — keduanya gratis,
  tanpa API key, sudah diverifikasi jalan, dan sekarang **auto-refresh saat
  dashboard dibuka**.
- **Buy Guard & Sell Guard** — logika reverse-pricing dan cost-of-carry
  persis sesuai spesifikasi.
- **Band skenario** (bagian 5.3) — jatuh ke lebar default eksplisit selama
  data historis harga belum cukup (>=30 titik), dengan flag terbuka di
  dashboard, bukan diam-diam memakai angka sembarangan.
- **Dashboard Streamlit** — Buy Guard, Sell Guard, data pasar/iklim, form
  input manual, dan pengiriman brief ke email (opsional, lihat di atas).
- **Daily Brief** — teks tersusun sesuai format spesifikasi, disimpan ke
  `data/brief-YYYY-MM-DD.txt` (lokal) dan bisa dikirim ke email.

## Yang BELUM dihubungkan (dan kenapa)

| Bagian | Status | Alasan |
|---|---|---|
| Feed harga futures ICE otomatis | Stub (`AUTOMATED_FEED_ENABLED = False`) di `src/ingest/price.py` | Perlu provider berbayar + verifikasi lisensi redistribusi (lihat spesifikasi 3.1). Ini keputusan legal/komersial |
| Pengiriman WhatsApp otomatis | Belum ada | Butuh WhatsApp Business API + izin eksplisit pemilik akun. Email sudah tersedia sebagai alternatif (lihat di atas) |
| Parameter biaya internal | Semua masih **placeholder 0** di `config/parameters.yaml` | Tujuh angka di spesifikasi bagian 11 belum dikonfirmasi pemilik data — output Buy/Sell Guard saat ini TIDAK BOLEH dipakai untuk keputusan nyata sampai ini diisi |
| Scheduler otomatis 24/7 | Tidak jalan di Streamlit Cloud | Perlu proses latar belakang terpisah (VPS/laptop selalu nyala) — lihat bagian "Batasan penting" di atas |

## Upload ulang ke GitHub (kalau pakai cara upload file di web)

Kalau repo lama Anda tercampur file `__pycache__`/`cgg.db`/`brief-*.txt`
(sisa upload sebelumnya), cara paling bersih: **hapus repo lama, buat baru**,
lalu upload ulang folder ini — `.gitignore` di sini tidak berlaku untuk cara
upload-via-web (GitHub mengunggah apa adanya), tapi folder ini sekarang
sudah bersih dari file-file itu, jadi upload ulang otomatis rapi selama
Anda tidak menyeret folder `__pycache__` (biasanya muncul lagi setelah
`python run_once.py` dijalankan lokal — jalankan dulu, baru hapus
`__pycache__` sebelum upload, atau upload sebelum menjalankan apa pun).

## Langkah berikutnya (Fase 0 di roadmap spesifikasi)

Isi tujuh angka di bagian 11 spesifikasi ke `config/parameters.yaml`,
lalu jalankan ulang `python run_once.py` — seluruh mesin keputusan langsung
memakai angka yang benar tanpa perlu ubah kode.
