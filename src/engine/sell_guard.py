# src/engine/sell_guard.py
"""
SELL GUARD — "Apakah menahan lot ini masih masuk akal?"
Lihat Spesifikasi Sistem, bagian 5.2.
"""


def hitung_cost_of_carry(hpp_lot: float, bulan: float, cfg: dict) -> dict:
    c = cfg["cost_of_carry"]
    biaya_modal = hpp_lot * (c["biaya_modal_tahunan_pct"] / 100 / 12) * bulan
    gudang      = c["gudang_rp_per_kg_bulan"] * bulan
    susut       = hpp_lot * (c["susut_pct_per_bulan"] / 100) * bulan
    risiko_grade = hpp_lot * (c["risiko_turun_grade_pct_per_bulan"] / 100) * bulan
    total = biaya_modal + gudang + susut + risiko_grade
    return {
        "biaya_modal": round(biaya_modal),
        "gudang": round(gudang),
        "susut": round(susut),
        "risiko_turun_grade": round(risiko_grade),
        "total_rp_kg": round(total),
    }


def sinyal_jual_tahan(
    harga_jual_hari_ini: float,
    hpp_lot: float,
    band_bawah_3bln: float,
    band_atas_3bln: float,
    cfg: dict,
) -> dict:
    carry = hitung_cost_of_carry(hpp_lot, bulan=1, cfg=cfg)
    impas = harga_jual_hari_ini + carry["total_rp_kg"]

    if band_bawah_3bln > impas:
        sinyal = "TAHAN"
        alasan = "Skenario terburuk pun masih menutupi biaya menahan."
    elif band_atas_3bln < impas:
        sinyal = "JUAL"
        alasan = "Skenario terbaik pun tidak menutupi biaya menahan."
    else:
        sinyal = "ZONA ABU-ABU"
        alasan = (
            "Band harga memotong titik impas. Keputusan bergantung pada "
            "kebutuhan kas, komitmen buyer, dan toleransi risiko."
        )

    return {
        "sinyal": sinyal,
        "alasan": alasan,
        "harga_impas_1_bulan": round(impas),
        "rincian_carry": carry,
        "margin_jika_jual_sekarang": round(harga_jual_hari_ini - hpp_lot),
    }


def alert_untuk_lot(lot: dict, deviasi_index_7hari_pct: float | None = None) -> list[str]:
    """Pemicu alert otomatis, lihat Spesifikasi Sistem tabel 5.2."""
    pesan = []
    umur = lot.get("umur_stok_hari") or 0
    if umur > 60:
        pesan.append(
            f"Lot {lot.get('lot_id')}: umur stok {umur} hari — cost of carry sudah "
            "melampaui premium grade — pertimbangkan lepas."
        )
    if deviasi_index_7hari_pct is not None and abs(deviasi_index_7hari_pct) > 5 and deviasi_index_7hari_pct < 0:
        pesan.append(
            f"Index turun {abs(deviasi_index_7hari_pct):.1f}% dalam 7 hari — "
            "reset harga beli lapangan segera."
        )
    return pesan
