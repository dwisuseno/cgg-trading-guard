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
