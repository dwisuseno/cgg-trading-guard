# src/engine/anomali.py
"""
Deteksi anomali pada seri harga bulanan historis -- dipakai untuk highlight
di grafik tren "Data Pasar & Iklim" plus analisa + rekomendasi singkat.

Pendekatan sama seperti band skenario (engine/scenario.py): kuantifikasi
statistik atas volatilitas historis (z-score dari log-return bulanan),
BUKAN model prediksi. Rekomendasi yang dikeluarkan juga sengaja generik --
mengarahkan balik ke Buy Guard/Sell Guard yang sudah ada, bukan sinyal beli/
jual baru yang berdiri sendiri. Sistem ini tidak memprediksi harga (lihat
spesifikasi 1.1).
"""
import math


def deteksi_anomali(seri: list[dict], ambang_z: float = 2.0) -> list[dict]:
    """
    seri: list of {"periode": "YYYY-MM", "index_usd_ton": float}, terurut
    lama -> baru (lihat db.historis_bulanan).

    Return list anomali (subset dari seri, urutan sama) dengan tambahan:
    pct_perubahan, arah, z_score, analisa, rekomendasi.
    """
    nilai = [b["index_usd_ton"] for b in seri if b.get("index_usd_ton")]
    if len(nilai) < 6:
        return []

    log_returns = []
    for i in range(1, len(nilai)):
        a, b = nilai[i - 1], nilai[i]
        if a and b and a > 0 and b > 0:
            log_returns.append(math.log(b / a))
    if len(log_returns) < 3:
        return []

    mean = sum(log_returns) / len(log_returns)
    var = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
    std = math.sqrt(var) if var > 0 else 0.0001

    hasil = []
    idx_return = 0
    for i in range(1, len(seri)):
        prev, curr = seri[i - 1], seri[i]
        a, b = prev.get("index_usd_ton"), curr.get("index_usd_ton")
        if not a or not b or a <= 0 or b <= 0:
            continue
        r = math.log(b / a)
        z = (r - mean) / std
        idx_return += 1
        if abs(z) < ambang_z:
            continue

        pct = (b / a - 1) * 100
        arah = "naik" if pct > 0 else "turun"

        if arah == "naik":
            analisa = (
                f"Index {arah} tajam {pct:+.1f}% dari bulan sebelumnya "
                f"(±{abs(z):.1f} standar deviasi dari pola volatilitas normal)."
            )
            rekomendasi = (
                "Untuk lot yang masih ditahan: cek tab Sell Guard, margin saat ini "
                "kemungkinan lebih baik daripada menahan lebih lama. Untuk pembelian "
                "baru: Buy Guard otomatis menyesuaikan turun karena margin makin "
                "ketat di harga tinggi -- jangan ikut menaikkan tawaran melebihi "
                "kolom basis tanpa alasan kuat."
            )
        else:
            analisa = (
                f"Index {arah} tajam {pct:+.1f}% dari bulan sebelumnya "
                f"(±{abs(z):.1f} standar deviasi dari pola volatilitas normal)."
            )
            rekomendasi = (
                "Bisa jadi peluang pembelian -- Buy Guard otomatis menaikkan batas "
                "harga beli maksimum saat index turun. Untuk stok yang sudah dibeli "
                "di harga lebih tinggi: cek Sell Guard, evaluasi apakah cost of carry "
                "masih tertutup sebelum memutuskan menahan lebih lama."
            )

        hasil.append({
            **curr,
            "pct_perubahan": round(pct, 1),
            "arah": arah,
            "z_score": round(z, 2),
            "analisa": analisa,
            "rekomendasi": rekomendasi,
        })

    return list(reversed(hasil))  # terbaru dulu
