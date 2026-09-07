# src/engine/korelasi.py
"""
Metodologi analisis korelasi-lag antara indikator iklim (ONI, curah hujan)
dan pergerakan harga -- teknik standar di riset dampak iklim-komoditas
(cross-correlation / lagged Pearson correlation), BUKAN model prediksi.
Hasilnya kuantitatif ("indikator X di bulan t berkorelasi r=... dengan
perubahan harga t+lag") -- manusia yang menafsirkan, sama seperti seluruh
sistem ini (lihat spesifikasi 1.1, P2).

Curah hujan diubah dulu jadi anomali z-score PER BULAN KALENDER (rata-rata
& stdev bulan itu di seluruh tahun data) supaya pola musiman hilang dan
skalanya sebanding dengan ONI (sama-sama kira-kira -3..+3) -- teknik standar
klimatologi, mirip prinsip Standardized Precipitation Index (SPI).
"""
import statistics
from collections import defaultdict


def zscore_anomali_bulanan(seri: dict[str, float]) -> dict[str, float]:
    """seri: {'YYYY-MM': nilai}. Return anomali z-score per periode, relatif
    ke rata-rata & stdev BULAN KALENDER yang sama di seluruh tahun."""
    per_bulan_kalender = defaultdict(list)
    for periode, v in seri.items():
        bulan = periode.split("-")[1]
        per_bulan_kalender[bulan].append(v)

    stat = {}
    for bulan, nilai in per_bulan_kalender.items():
        mean = statistics.mean(nilai)
        std = statistics.stdev(nilai) if len(nilai) >= 2 else 0.0
        stat[bulan] = (mean, std)

    hasil = {}
    for periode, v in seri.items():
        bulan = periode.split("-")[1]
        mean, std = stat[bulan]
        hasil[periode] = round((v - mean) / std, 2) if std > 0 else 0.0
    return hasil


def perubahan_pct_bulanan(seri: dict[str, float]) -> dict[str, float]:
    """% perubahan harga vs bulan sebelumnya, per periode (butuh urutan waktu)."""
    periode_urut = sorted(seri.keys())
    hasil = {}
    for i in range(1, len(periode_urut)):
        a, b = seri[periode_urut[i - 1]], seri[periode_urut[i]]
        if a and a != 0:
            hasil[periode_urut[i]] = (b / a - 1) * 100
    return hasil


def korelasi_lag(indikator: dict[str, float], perubahan_harga: dict[str, float],
                  lag_maks: int = 6, min_titik: int = 24) -> list[dict]:
    """
    Untuk tiap lag L (0..lag_maks bulan): cocokkan nilai indikator bulan t
    dengan % perubahan harga bulan t+L -- "apakah indikator sekarang
    berkorelasi dengan pergerakan harga L bulan kemudian". Return list
    {lag_bulan, r, n} terurut dari |r| terbesar.
    """
    periode_urut = sorted(indikator.keys())
    idx = {p: i for i, p in enumerate(periode_urut)}
    hasil = []
    for lag in range(0, lag_maks + 1):
        pasangan = []
        for p, i in idx.items():
            target = periode_urut[i + lag] if i + lag < len(periode_urut) else None
            if target and target in perubahan_harga:
                pasangan.append((indikator[p], perubahan_harga[target]))
        if len(pasangan) < min_titik:
            continue
        xs = [a for a, b in pasangan]
        ys = [b for a, b in pasangan]
        try:
            r = statistics.correlation(xs, ys)
        except statistics.StatisticsError:
            r = 0.0
        hasil.append({"lag_bulan": lag, "r": round(r, 3), "n": len(pasangan)})
    hasil.sort(key=lambda h: abs(h["r"]), reverse=True)
    return hasil


def kekuatan_korelasi(r: float) -> str:
    ar = abs(r)
    if ar >= 0.5:
        return "kuat"
    if ar >= 0.3:
        return "sedang"
    if ar >= 0.1:
        return "lemah"
    return "tidak signifikan"
