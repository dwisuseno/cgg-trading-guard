# src/ingest/price.py
"""
Harga dunia — ini bagian yang perlu perhatian khusus (Spesifikasi Sistem 3.1).

ICCO tidak menyediakan API gratis, dan data futures ICE resmi (metodologi
index ICCO: rata-rata 3 bulan kontrak London+NY terdekat, kurs forward 6
bulan) ada di balik provider berbayar dengan lisensi redistribusi yang
harus diverifikasi dulu -- itu TIDAK diaktifkan di sini.

Strategi tiga lapis:
  1 (otomatis, PROXY)  Yahoo Finance (kontrak depan/front-month ICE Cocoa NY,
                        simbol CC=F) + kurs USD/IDR dari open.er-api.com.
                        Keduanya gratis, tanpa API key, dan sudah dites jalan
                        (2026-09-07). Berjalan sendiri tiap hari via
                        scheduler.pagi()/dashboard auto-bootstrap.
                        PENTING: ini BUKAN index resmi ICCO -- hanya kontrak
                        depan NY tunggal, bukan rata-rata 3 bulan London+NY.
                        Cukup baik untuk sinyal harian, tapi beri label jelas
                        di UI ("proxy", bukan "resmi") dan tetap sediakan
                        field icco_resmi_usd untuk kalibrasi manual berkala.
  2 (kalibrasi)         ICCO daily price resmi yang diumumkan publik, dipakai
                        untuk memvalidasi lapis 1 lewat field icco_resmi_usd
                        -- masukkan manual saat Anda sempat cek situs ICCO.
  3 (fallback)          Kalau lapis 1 gagal (Yahoo/FX down, format berubah,
                        dsb): pakai nilai terakhir yang valid di DB (flag
                        'fallback' + stale=True), atau input manual lewat
                        dashboard. Sistem tidak boleh mati karena satu
                        sumber data bermasalah.
"""
from datetime import datetime, date

import requests

AUTOMATED_FEED_ENABLED = True

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_SYMBOL_NY = "CC=F"  # ICE Cocoa futures, New York, kontrak depan (continuous)
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CGGTradingGuard/1.0)"}

FX_URL = "https://open.er-api.com/v6/latest/USD"  # gratis, tanpa API key


def _fetch_yahoo_futures_usd_per_ton(symbol: str = YAHOO_SYMBOL_NY) -> float:
    r = requests.get(
        YAHOO_CHART_URL.format(symbol=symbol),
        params={"interval": "1d", "range": "5d"},
        headers=YAHOO_HEADERS,
        timeout=20,
    )
    r.raise_for_status()
    result = r.json()["chart"]["result"][0]
    closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
    if not closes:
        raise ValueError("Yahoo Finance tidak mengembalikan data close.")
    return float(closes[-1])


def _fetch_kurs_usd_idr() -> float:
    r = requests.get(FX_URL, timeout=20)
    r.raise_for_status()
    idr = r.json().get("rates", {}).get("IDR")
    if not idr:
        raise ValueError("Kurs IDR tidak ditemukan di respons open.er-api.com.")
    return float(idr)


def ambil_index_otomatis() -> dict | None:
    """
    Lapis 1 (proxy). Mengembalikan dict {ice_ny_usd_ton, kurs_usd_idr} kalau
    kedua sumber berhasil diambil, atau None kalau salah satu gagal --
    caller (ambil_harga_hari_ini) yang menangani fallback ke lapis berikutnya.
    Tidak pernah melempar exception ke pemanggil.
    """
    if not AUTOMATED_FEED_ENABLED:
        return None
    try:
        ny = _fetch_yahoo_futures_usd_per_ton()
        kurs = _fetch_kurs_usd_idr()
    except Exception:
        return None
    if not ny or not kurs:
        return None
    return {"ice_ny_usd_ton": ny, "kurs_usd_idr": kurs}


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
    Menyimpan satu baris harga hari ini. Dipakai baik oleh input manual
    (Layer 3, koordinator lewat dashboard) maupun oleh hasil fetch otomatis
    (Layer 1, lihat ambil_harga_hari_ini) -- keduanya lewat fungsi yang sama
    supaya perhitungan index_idr_per_kg konsisten di kedua jalur.

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
    Orkestrasi harian: coba lapis 1 (Yahoo Finance + FX, otomatis) dan
    LANGSUNG SIMPAN kalau berhasil. Kalau gagal/mati, pakai nilai terakhir
    yang valid di DB dengan flag 'fallback' + stale=True -- tidak pernah
    mati total hanya karena satu sumber data bermasalah. Input manual lewat
    dashboard selalu tersedia sebagai override kapan pun.
    """
    from .. import db

    otomatis = ambil_index_otomatis()
    if otomatis:
        return catat_harga_manual(
            conn,
            ice_ny_usd_ton=otomatis["ice_ny_usd_ton"],
            kurs_usd_idr=otomatis["kurs_usd_idr"],
            sumber="otomatis (Yahoo Finance CC=F + open.er-api.com, proxy — bukan index resmi ICCO)",
        )

    terakhir = db.latest_market_price(conn)
    if terakhir is None:
        return {
            "status": "KOSONG",
            "pesan": (
                "Belum ada data harga sama sekali, dan fetch otomatis gagal. Jalankan "
                "price.catat_harga_manual(conn, ...) dengan angka hari ini, atau isi "
                "lewat dashboard (tab 'Input Manual')."
            ),
        }
    return {**terakhir, "sumber": "fallback", "stale": True}
