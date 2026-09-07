# src/engine/musiman.py
"""
Musim & Panen -- dari catatan tim (2026-09): tiga pertimbangan (pergerakan
index, perkembangan panen, kondisi iklim di sabuk produsen) yang membentuk
Dampak (apa yang sedang terjadi) dan Antisipasi (apa yang sebaiknya
dilakukan) untuk Buy Guard & Sell Guard.

Modul ini SENGAJA hanya memberi CATATAN kualitatif, bukan mengubah angka
Buy/Sell Guard secara otomatis -- beda dengan ONI (band_skenario) yang sudah
punya dasar ambang meteorologi yang mapan, fase panen di sini belum punya
data historis CGG untuk dikalibrasi. Menambah pengali tanpa dasar itu = P2
dilanggar sendiri (band jadi ilusi presisi). Tinjau ulang jadi kuantitatif
setelah beberapa musim data lot_realisasi terkumpul (lihat Fase 2 roadmap).
"""
from datetime import date


def _dalam_rentang(bulan: int, mulai: int, selesai: int) -> bool:
    if mulai <= selesai:
        return mulai <= bulan <= selesai
    return bulan >= mulai or bulan <= selesai  # rentang yang melewati akhir tahun


def fase_panen_lokal(cfg: dict, tanggal: date | None = None) -> dict:
    tanggal = tanggal or date.today()
    m = tanggal.month
    mp = cfg["musim_panen"]["lokal"]
    pu, ps = mp["panen_utama"], mp["panen_sela"]

    if _dalam_rentang(m, pu["mulai_bulan"], pu["selesai_bulan"]):
        return {
            "fase": "panen_utama",
            "label": "Panen Utama",
            "dampak": "Volume lokal biasanya naik -- pasokan lebih longgar, leverage tawar CGG membaik.",
            "antisipasi": "Pertimbangkan volume pembelian lebih besar; disiplin di harga konservatif karena pasokan sedang tidak langka.",
        }
    if _dalam_rentang(m, ps["mulai_bulan"], ps["selesai_bulan"]):
        return {
            "fase": "panen_sela",
            "label": "Panen Sela",
            "dampak": "Volume sedang, mutu lebih bervariasi dibanding panen utama.",
            "antisipasi": "Perketat pengecekan mutu (kadar air, bean count) sebelum sepakat harga di atas basis.",
        }
    return {
        "fase": "antar_panen",
        "label": "Antar-Panen",
        "dampak": "Volume lokal biasanya rendah -- persaingan dengan pengepul lain lebih ketat.",
        "antisipasi": "Waspada tekanan naik dari petani/pengepul; kalau tawaran > basis, wajib alasan tertulis (aturan Buy Guard tetap berlaku).",
    }


def ringkasan_dampak_global(harga: dict | None, cuaca_global: dict) -> list[str]:
    """
    Rangkuman satu-dua baris per titik pantau global (Afrika Barat), untuk
    ditampilkan sebagai konteks "kenapa index bergerak begini" -- bukan
    prediksi, sekadar korelasi kualitatif yang harus dibaca manusia.
    """
    baris = []
    for kode, data in cuaca_global.items():
        if not data:
            continue
        risiko = data.get("risiko_proses", "?")
        hujan = data.get("hujan_14hari_mm", "?")
        baris.append(
            f"{kode}: hujan 14hr {hujan}mm (risiko proses {risiko}) -- "
            f"hujan berlebih di sabuk produsen historisnya mendahului kekhawatiran "
            f"pasokan global 2-4 minggu ke depan."
        )
    return baris
