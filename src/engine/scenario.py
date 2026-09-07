# src/engine/scenario.py
"""
Pembentukan band skenario — kuantifikasi ketidakpastian, BUKAN ramalan arah.
Lihat Spesifikasi Sistem, bagian 5.3.

Memakai volatilitas historis (stdev log-return harian) + penyesuaian regime
iklim (ONI). Saat data historis belum cukup (sistem baru mulai), band jatuh
ke lebar default eksplisit dari config, dengan flag `data_cukup=False` supaya
dashboard bisa menandainya secara terbuka alih-alih diam-diam memakai angka
yang tidak berdasar.
"""
import math


def _pengali_regime(oni: float, cfg_band: dict) -> float:
    regime = cfg_band["pengali_regime"]
    if abs(oni) >= regime["oni_tinggi"]["ambang_abs_oni"]:
        return regime["oni_tinggi"]["pengali"]
    if abs(oni) >= regime["oni_sedang"]["ambang_abs_oni"]:
        return regime["oni_sedang"]["pengali"]
    return regime["netral"]["pengali"]


def hitung_band(index_terkini: float, harga_historis: list[float], oni: float, cfg: dict) -> dict:
    """
    harga_historis: list index_idr_per_kg terurut, terbaru dulu (lihat db.price_history).
    """
    cfg_band = cfg["band_skenario"]
    pengali = _pengali_regime(oni, cfg_band)
    n_minimum = cfg_band["minimum_titik_data"]

    if len(harga_historis) >= n_minimum:
        log_returns = []
        for i in range(len(harga_historis) - 1):
            a, b = harga_historis[i], harga_historis[i + 1]
            if a and b and a > 0 and b > 0:
                log_returns.append(math.log(a / b))
        if len(log_returns) >= 2:
            mean = sum(log_returns) / len(log_returns)
            var = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
            vol_harian = math.sqrt(var)
            vol_n_hari = vol_harian * math.sqrt(len(harga_historis))
            lebar = cfg_band["confidence_z"] * vol_n_hari
            data_cukup = True
        else:
            lebar = cfg_band["default_lebar_pct"]
            data_cukup = False
    else:
        lebar = cfg_band["default_lebar_pct"]
        data_cukup = False

    lebar_final = lebar * pengali
    return {
        "index_tengah": round(index_terkini),
        "band_bawah": round(index_terkini * (1 - lebar_final)),
        "band_atas": round(index_terkini * (1 + lebar_final)),
        "lebar_pct": round(lebar_final * 100, 2),
        "pengali_regime": pengali,
        "data_cukup": data_cukup,
        "jumlah_titik_data": len(harga_historis),
        "catatan": (
            None
            if data_cukup
            else (
                f"Band memakai lebar default {cfg_band['default_lebar_pct']*100:.0f}% "
                f"(butuh >= {n_minimum} titik data harga historis; baru ada {len(harga_historis)}). "
                "Ini BUKAN kalibrasi — perketat setelah data cukup."
            )
        ),
    }
