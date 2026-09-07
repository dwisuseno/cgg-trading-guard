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


# Musim 3-bulan NOAA -> bulan kalender tengahnya (konvensi meteorologi standar).
_SEASON_KE_BULAN = {
    "DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
    "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12,
}


def ambil_oni_historis() -> list[dict]:
    """
    Seluruh seri ONI historis (919 baris sejak 1950 saat dites 2026-09-07),
    dipetakan ke 'YYYY-MM' (bulan kalender tengah musim) supaya sejajar
    dengan seri harga ICCO bulanan untuk grafik tren gabungan.
    """
    r = requests.get(ONI_URL, timeout=30)
    r.raise_for_status()
    baris = [b.split() for b in r.text.strip().split("\n")[1:] if b.strip()]
    hasil = []
    for seas, yr, total, anom in baris:
        bulan = _SEASON_KE_BULAN.get(seas)
        if not bulan:
            continue
        try:
            oni = float(anom)
            tahun = int(yr)
        except ValueError:
            continue
        if oni >= 0.5:
            fase = "el_nino"
        elif oni <= -0.5:
            fase = "la_nina"
        else:
            fase = "netral"
        hasil.append({"periode": f"{tahun:04d}-{bulan:02d}", "oni": oni, "fase": fase})
    hasil.sort(key=lambda x: x["periode"])
    return hasil
