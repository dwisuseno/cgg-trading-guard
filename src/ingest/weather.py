# src/ingest/weather.py
"""
Cuaca lokal — Open-Meteo. Gratis, tanpa API key, tanpa registrasi.
Dua kegunaan berbeda (jangan dicampur): sinyal pasokan, dan sinyal risiko
proses pengeringan/fermentasi. Lihat Spesifikasi Sistem, bagian 3.3.
"""
import requests

URL = "https://api.open-meteo.com/v1/forecast"   # gratis, tanpa API key
# Diverifikasi 2026-09-07: endpoint aktif.


def ambil_cuaca(lat: float, lon: float) -> dict:
    r = requests.get(URL, params={
        "latitude": lat,
        "longitude": lon,
        "daily": "precipitation_sum,relative_humidity_2m_mean,shortwave_radiation_sum",
        "forecast_days": 14,
        "timezone": "Asia/Makassar",
    }, timeout=30)
    r.raise_for_status()
    d = r.json()["daily"]
    hujan_14 = sum(v for v in d["precipitation_sum"] if v is not None)

    if hujan_14 > 200:
        risiko = "tinggi"
    elif hujan_14 > 100:
        risiko = "sedang"
    else:
        risiko = "rendah"

    return {
        "hujan_hari_ini_mm": d["precipitation_sum"][0],
        "hujan_14hari_mm": round(hujan_14, 1),
        "kelembapan_pct": d["relative_humidity_2m_mean"][0],
        "radiasi_mj": d["shortwave_radiation_sum"][0],
        "risiko_proses": risiko,
    }


ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"  # gratis, tanpa API key, historis sejak ~1940an
# Diverifikasi 2026-09-07: 20 tahun data (2005-2026) untuk satu titik ditarik dalam ~2 detik.


def ambil_curah_hujan_historis_bulanan(lat: float, lon: float, mulai: str, selesai: str) -> dict:
    """
    Curah hujan harian dari arsip Open-Meteo, diagregasi jadi TOTAL BULANAN
    (mm). mulai/selesai format 'YYYY-MM-DD'. Return {"YYYY-MM": total_mm}.
    Dipakai untuk overlay grafik tren (lihat engine/korelasi.py untuk
    perhitungan anomali & korelasi-nya).
    """
    r = requests.get(ARCHIVE_URL, params={
        "latitude": lat, "longitude": lon,
        "start_date": mulai, "end_date": selesai,
        "daily": "precipitation_sum",
        "timezone": "UTC",
    }, timeout=60)
    r.raise_for_status()
    d = r.json()["daily"]
    per_bulan: dict[str, float] = {}
    for tgl, hujan in zip(d["time"], d["precipitation_sum"]):
        if hujan is None:
            continue
        periode = tgl[:7]  # 'YYYY-MM-DD' -> 'YYYY-MM'
        per_bulan[periode] = per_bulan.get(periode, 0.0) + hujan
    return {k: round(v, 1) for k, v in per_bulan.items()}
