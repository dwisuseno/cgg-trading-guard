# src/ingest/climate.py
"""
Iklim makro — ONI (Oceanic Nino Index) dari NOAA. Gratis, tanpa API key.
Update bulanan (rata-rata bergerak 3 bulan, secara definisi bukan harian).
Lihat Spesifikasi Sistem, bagian 3.2.
"""
import requests

ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
# Diverifikasi 2026-09-07: endpoint aktif, format teks kolom (SEAS YR TOTAL ANOM).


def ambil_oni() -> dict:
    r = requests.get(ONI_URL, timeout=30)
    r.raise_for_status()
    baris = [b.split() for b in r.text.strip().split("\n")[1:] if b.strip()]
    terakhir = baris[-1]                    # SEAS YR TOTAL ANOM
    oni = float(terakhir[3])
    if oni >= 0.5:
        fase = "el_nino"
    elif oni <= -0.5:
        fase = "la_nina"
    else:
        fase = "netral"
    return {"seas": terakhir[0], "tahun": int(terakhir[1]), "oni": oni, "fase": fase}
