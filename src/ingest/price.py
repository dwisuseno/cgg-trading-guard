# src/ingest/price.py
"""
Harga dunia — ini bagian yang perlu perhatian khusus (Spesifikasi Sistem 3.1).

ICCO tidak menyediakan API gratis. Strategi tiga lapis:
  1 (utama)     data futures ICE (CC = New York, C/LCC = London), 3 bulan
                kontrak terdekat -> BELUM diaktifkan di sini. Perlu provider
                berbayar (Nasdaq Data Link / commodities-api / feed broker)
                DAN verifikasi lisensi redistribusi SEBELUM diaktifkan. Ini
                masalah legal, bukan teknis -- lihat README.
  2 (kalibrasi) ICCO daily price publik, dipakai untuk memvalidasi lapis 1,
                bukan sebagai feed utama -> belum ada scraper otomatis;
                masukkan manual saat tersedia.
  3 (fallback)  input manual oleh koordinator -> SELALU tersedia, dan yang
                aktif dipakai oleh sistem hari ini.

Tidak ada panggilan ke API berbayar apa pun di modul ini sampai kredensial
dan status lisensi dikonfirmasi.
"""
from datetime import datetime, date

AUTOMATED_FEED_ENABLED = False  # ubah setelah provider + lisensi terverifikasi


def ambil_index_otomatis():
    """
    Placeholder untuk lapis 1. Sengaja TIDAK memanggil API apa pun sampai
    provider dipilih dan lisensi redistribusi terverifikasi (lihat README).
    """
    if not AUTOMATED_FEED_ENABLED:
        return None
    raise NotImplementedError(
        "Feed otomatis belum dikonfigurasi. Set AUTOMATED_FEED_ENABLED=True "
        "dan implementasikan pemanggilan provider setelah lisensi terverifikasi."
    )


def catat_harga_manual(
    conn,
    tanggal: str | None = None,
    ice_ny_usd_ton: float | None = None,
    ice_london_gbp_ton: float | None = None,
    kurs_usd_idr: float | None = None,
    icco_resmi_usd: float | None = None,
    sumber: str = "manual",
):
    """
    Layer 3 — WAJIB selalu tersedia. Dipanggil koordinator (atau operator)
    saat memasukkan harga hari ini secara manual dari sumber yang mereka
    percaya (situs/medsos ICCO, broker, dsb).

    index_idr_per_kg dihitung dari index_rekonstruksi_usd (USD/ton) x kurs,
    dibagi 1000 untuk konversi ton -> kg.
    """
    from .. import db

    tanggal = tanggal or date.today().isoformat()

    kandidat = [v for v in (ice_ny_usd_ton, ice_london_gbp_ton) if v]
    index_usd = sum(kandidat) / len(kandidat) if kandidat else None

    deviasi_pct = None
    if index_usd and icco_resmi_usd:
        deviasi_pct = round((index_usd - icco_resmi_usd) / icco_resmi_usd * 100, 2)

    index_idr_per_kg = None
    if index_usd and kurs_usd_idr:
        index_idr_per_kg = round(index_usd * kurs_usd_idr / 1000, 2)

    row = {
        "tanggal": tanggal,
        "ice_ny_usd_ton": ice_ny_usd_ton,
        "ice_london_gbp_ton": ice_london_gbp_ton,
        "index_rekonstruksi_usd": index_usd,
        "icco_resmi_usd": icco_resmi_usd,
        "deviasi_pct": deviasi_pct,
        "kurs_usd_idr": kurs_usd_idr,
        "index_idr_per_kg": index_idr_per_kg,
        "sumber": sumber,
        "diambil_pada": datetime.now().isoformat(timespec="seconds"),
    }
    db.upsert(conn, "market_price", row)
    return row


def ambil_harga_hari_ini(conn):
    """
    Orkestrasi: coba lapis 1, jika mati/tidak aktif -> pakai nilai terakhir
    yang valid di DB dengan flag 'fallback' + stale=True, supaya sistem
    tidak pernah mati total hanya karena satu sumber data bermasalah.
    """
    from .. import db

    otomatis = ambil_index_otomatis()
    if otomatis:
        return otomatis

    terakhir = db.latest_market_price(conn)
    if terakhir is None:
        return {
            "status": "KOSONG",
            "pesan": (
                "Belum ada data harga sama sekali. Jalankan "
                "price.catat_harga_manual(conn, ...) dengan angka hari ini."
            ),
        }
    return {**terakhir, "sumber": "fallback", "stale": True}
