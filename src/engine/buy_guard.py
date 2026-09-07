# src/engine/buy_guard.py
"""
BUY GUARD — harga beli maksimum per grade, per skenario, per titik terima.
Reverse pricing (P1): mundur dari harga jual yang bisa diraih, bukan maju
dari biaya + margin harapan. Lihat Spesifikasi Sistem, bagian 5.1.
"""
from dataclasses import dataclass


@dataclass
class HasilBuyGuard:
    grade: str
    skenario: str
    harga_jual_referensi: float
    total_biaya: float
    harga_maks_kering: float
    harga_maks_basah: float
    rendemen_dipakai: float


def hitung_harga_beli_maks(
    index_idr_per_kg: float,
    grade: str,
    skenario: str,
    segmen_target: str,
    kode_titik: str,
    cfg: dict,
    oni: float,
) -> HasilBuyGuard:
    """
    Reverse pricing: mundur dari harga jual, bukan maju dari biaya.
    Ini pembalikan arah aritmatika yang menjadi inti sistem.
    """
    # 1. Harga jual yang bisa diraih
    premium = cfg["segmen_jual"][segmen_target]["premium_thd_index"]
    harga_jual = index_idr_per_kg * (1 + premium)

    # 2. Margin target — dinaikkan saat ketidakpastian iklim tinggi
    margin_pct = cfg["margin_target"][grade]
    if abs(oni) >= 1.0:
        margin_pct += cfg["margin_target"]["penalti_ketidakpastian_tinggi"]
    margin = harga_jual * margin_pct

    # 3. Seluruh biaya per kg kering
    # Struktur: Harga Jual = Biaya Pokok Produksi (Raw Material, di-solve di
    # langkah 4 di bawah) + Overhead Cost + Other Cost + Margin.
    overhead_cost = cfg["overhead_cost"]["nilai_rp_kg"]
    other_cost = cfg["other_cost"]["nilai_rp_kg"]
    titik = next(
        t for t in cfg["titik_terima"] if t["kode"] == kode_titik
    )
    other_cost += titik["freight_tambahan_rp_kg"]

    total_biaya = margin + overhead_cost + other_cost

    # 4. Sisa yang boleh dibayarkan ke petani
    sisa_kering = harga_jual - total_biaya
    susut_sortasi = cfg["rendemen"]["susut_sortasi_pct"] / 100
    harga_maks_kering = sisa_kering * (1 - susut_sortasi)

    # 5. Konversi ke basis basah
    rendemen = cfg["rendemen"]["basah_ke_kering"][skenario]
    harga_maks_basah = harga_maks_kering / rendemen

    return HasilBuyGuard(
        grade=grade,
        skenario=skenario,
        harga_jual_referensi=round(harga_jual),
        total_biaya=round(total_biaya),
        harga_maks_kering=round(harga_maks_kering),
        harga_maks_basah=round(harga_maks_basah),
        rendemen_dipakai=rendemen,
    )


def bandingkan_jalur(hasil_basah, hasil_kering, tawar_basah, tawar_kering):
    """
    Jalur mana yang lebih menguntungkan HARI INI, pada harga yang
    benar-benar ditawarkan — bukan pada asumsi.
    """
    hpp_via_basah = tawar_basah * hasil_basah.rendemen_dipakai
    hpp_via_kering = tawar_kering
    return {
        "hpp_kering_setara_dari_basah": round(hpp_via_basah),
        "hpp_beli_kering_langsung": round(hpp_via_kering),
        "jalur_lebih_baik": "basah" if hpp_via_basah < hpp_via_kering else "kering",
        "selisih_rp_kg": round(abs(hpp_via_basah - hpp_via_kering)),
    }


def hitung_semua_skenario(index_idr_per_kg: float, kode_titik: str, cfg: dict, oni: float):
    """
    Menghasilkan matriks lengkap: 3 grade x 3 skenario, untuk satu titik terima.
    Segmen target dipetakan per grade (grade tinggi -> segmen dengan syarat mutu lebih ketat).
    """
    segmen_per_grade = {
        "premium": "artisan",
        "medium": "pabrik_chocolate_maker",
        "low": "trader_asalan",
    }
    hasil = []
    for grade, segmen in segmen_per_grade.items():
        for skenario in ("konservatif", "basis", "optimis"):
            hasil.append(
                hitung_harga_beli_maks(
                    index_idr_per_kg=index_idr_per_kg,
                    grade=grade,
                    skenario=skenario,
                    segmen_target=segmen,
                    kode_titik=kode_titik,
                    cfg=cfg,
                    oni=oni,
                )
            )
    return hasil
