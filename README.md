# CGG Trading Guard

Implementasi kerja dari `CGG-Trading-Guard-Spesifikasi-Sistem.md`. Sistem
penasihat (bukan prediktor, bukan auto-trader) untuk dua keputusan: harga
beli maksimum ke petani, dan jual-vs-tahan untuk lot yang sudah dibeli.

## Menjalankan

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

## Yang sudah benar-benar berfungsi hari ini

- **Database SQLite** — skema lengkap sesuai spesifikasi bagian 6.
- **Ingest iklim (ONI/NOAA)** dan **cuaca (Open-Meteo)** — keduanya gratis,
  tanpa API key, dan sudah diverifikasi jalan dari laptop ini.
- **Buy Guard & Sell Guard** — logika reverse-pricing dan cost-of-carry
  persis sesuai spesifikasi, teruji dengan data dummy.
- **Band skenario** (bagian 5.3) — jatuh ke lebar default eksplisit selama
  data historis harga belum cukup (>=30 titik), dengan flag terbuka di
  dashboard, bukan diam-diam memakai angka sembarangan.
- **Dashboard Streamlit** — Buy Guard, Sell Guard, data pasar/iklim, dan
  form input manual.
- **Daily Brief** — teks tersusun sesuai format spesifikasi, disimpan ke
  `data/brief-YYYY-MM-DD.txt`.

## Yang BELUM dihubungkan (dan kenapa)

| Bagian | Status | Alasan |
|---|---|---|
| Feed harga futures ICE otomatis | Stub (`AUTOMATED_FEED_ENABLED = False`) di `src/ingest/price.py` | Perlu provider berbayar + verifikasi lisensi redistribusi (lihat spesifikasi 3.1). Ini keputusan legal/komersial, bukan sesuatu yang bisa diaktifkan begitu saja |
| Pengiriman WhatsApp/email otomatis | Brief hanya dicetak + disimpan ke file | Butuh kredensial API (WhatsApp Business API / SMTP) dan izin eksplisit pemilik akun |
| Parameter biaya internal | Semua masih **placeholder 0** di `config/parameters.yaml` | Tujuh angka di spesifikasi bagian 11 belum dikonfirmasi pemilik data — output Buy/Sell Guard saat ini TIDAK BOLEH dipakai untuk keputusan nyata sampai ini diisi |

## Langkah berikutnya (Fase 0 di roadmap spesifikasi)

Isi tujuh angka di bagian 11 spesifikasi ke `config/parameters.yaml`,
lalu jalankan ulang `python run_once.py` — seluruh mesin keputusan langsung
memakai angka yang benar tanpa perlu ubah kode.
