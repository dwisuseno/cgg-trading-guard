# src/ingest/supply_demand.py
"""
Ringkasan Supply & Demand Balance global kakao (Cocoa Production, Grindings,
Stocks, Surplus/Deficit) -- diambil dari siaran pers "Quarterly Bulletin of
Cocoa Statistics" ICCO (icco.org), rilis 4x/tahun: Februari, Mei, Agustus,
November.

PENTING -- batasan jujur, baca sebelum percaya hasilnya begitu saja:
Sejak 2025 ICCO memindahkan bulletin LENGKAP (Excel/PDF, data historis penuh
per negara) ke balik langganan berbayar (lihat icco.org/statistics, bagian
"Statistical Information and Publications - Access Update"). Yang masih
gratis cuma siaran pers ringkasannya di halaman berita -- dan TIDAK
terstruktur seperti tabel harga bulanan (bandingkan dengan price_historis.py
yang menarik tabel wpDataTables asli). Redaksi kalimatnya berubah-ubah tiap
rilis: kadang "World Gross Production increased by X% ... to Y million
tonnes", kadang "production and grindings are estimated to be X and Y",
kadang cuma tabel ringkasan yang tidak diparse versi ini.

Dites manual 2026-09-08 terhadap 3 rilis terakhir:
- Agustus 2026: berhasil penuh (produksi, grindings, surplus/defisit, stok, rasio).
- Mei 2026: sebagian (produksi/grindings/surplus dapat; stok & rasio tidak --
  ada di tabel ringkasan bulletin yang formatnya beda, tidak diparse versi ini).
- Februari 2026: tidak dapat sama sekali (redaksi kalimat beda lagi).

Karena itu fungsi ini dirancang sebagai ASISTEN pengisi form (prefill), BUKAN
pipeline otomatis yang langsung menulis ke database -- selalu tampilkan hasilnya
di form yang wajib dikonfirmasi/dikoreksi manusia sebelum disimpan (P4).
"""
import re

import requests

SEARCH_URL = "https://www.icco.org/?s=Quarterly+Bulletin+of+Cocoa+Statistics"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CGGTradingGuard/1.0; +internal decision-support tool)"}

_BULAN = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def _bersihkan_html(html: str) -> str:
    teks = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    teks = re.sub(r"<style.*?</style>", " ", teks, flags=re.S | re.I)
    teks = re.sub(r"<[^>]+>", " ", teks)
    teks = teks.replace("&#8217;", "'").replace("&#8211;", "-").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", teks)


def _url_bulletin_terbaru(session: requests.Session) -> str:
    r = session.get(SEARCH_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    urls = re.findall(
        r'href="(https://www\.icco\.org/[a-z0-9-]*quarterly-bulletin-of-cocoa-statistics/?)"',
        r.text,
    )
    if not urls:
        raise ValueError(
            "Tidak menemukan link Quarterly Bulletin terbaru -- struktur halaman "
            "pencarian ICCO mungkin sudah berubah."
        )
    return urls[0]


def _periode_dari_url(url: str) -> str | None:
    m = re.search(r"/([a-z]+)-(\d{4})-quarterly-bulletin", url)
    if not m:
        return None
    bulan = _BULAN.get(m.group(1).lower())
    return f"{m.group(2)}-{bulan}" if bulan else None


def _ke_ribu_ton(angka_str: str, satuan: str | None) -> float:
    angka = float(angka_str.replace(",", ""))
    if satuan and satuan.lower().startswith("million"):
        return round(angka * 1000, 1)
    if satuan and satuan.lower().startswith("thousand"):
        return round(angka, 1)
    return round(angka / 1000, 1)  # tanpa satuan eksplisit -> asumsi angka mentah dalam ton


def _cari_naik_turun(teks: str, entitas: str):
    """Pola 'World Gross Production increased by 8.5% ... to 4.733 million tonnes'."""
    pat = re.compile(
        rf"{entitas}[^.]{{0,20}}?(increased|rose|grew|fell|decreased|dropped)\s+by\s+"
        rf"(?:almost\s+)?([\d.]+)%[^.]{{0,60}}?to\s+([\d][\d,.]*)\s*(million|thousand)?\s*tonnes",
        re.IGNORECASE,
    )
    m = pat.search(teks)
    if not m:
        return None, None
    arah, pct, angka, satuan = m.groups()
    tanda = -1 if arah.lower() in ("fell", "decreased", "dropped") else 1
    return tanda * float(pct), _ke_ribu_ton(angka, satuan)


def _cari_gabungan_produksi_grindings(teks: str):
    """Pola 'production and grindings are estimated to be 4.723 million tonnes and 4.628 million tonnes'."""
    pat = re.compile(
        r"production and grindings are (?:now\s+)?estimated to be\s+"
        r"([\d][\d,.]*)\s*(million|thousand)?\s*tonnes\s+and\s+([\d][\d,.]*)\s*(million|thousand)?\s*tonnes",
        re.IGNORECASE,
    )
    m = pat.search(teks)
    if not m:
        return None, None
    ang1, sat1, ang2, sat2 = m.groups()
    return _ke_ribu_ton(ang1, sat1), _ke_ribu_ton(ang2, sat2)


def _cari_surplus_defisit(teks: str):
    pat = re.compile(
        r"supply\s+(surplus|deficit)[^.]{0,60}?(?:estimated as|revised to|of)\s+"
        r"([\d][\d,.]*)\s*(million|thousand)?\s*tonnes",
        re.IGNORECASE,
    )
    m = pat.search(teks)
    if not m:
        return None
    jenis, angka, satuan = m.groups()
    nilai = _ke_ribu_ton(angka, satuan)
    return -nilai if jenis.lower() == "deficit" else nilai


def _cari_stok(teks: str):
    pat = re.compile(
        r"(?:End-of-season\s+)?[Ss]tocks[^.]{0,20}?(increased|rose|grew|fell|decreased|dropped)"
        r"[^.]{0,60}?to\s+([\d][\d,.]*)\s*(million|thousand)?\s*tonnes",
        re.IGNORECASE,
    )
    m = pat.search(teks)
    if not m:
        return None
    _, angka, satuan = m.groups()
    return _ke_ribu_ton(angka, satuan)


def _cari_rasio(teks: str):
    m = re.search(r"stocks-to-grindings ratio[^\d]{0,20}([\d]+(?:\.\d+)?)\s*%", teks, re.IGNORECASE)
    return float(m.group(1)) if m else None


def _cari_musim(teks: str) -> str | None:
    m = re.search(r"data for the (\d{4}/\d{2}) season are estimated", teks, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"for the (\d{4}/\d{2}) cocoa year", teks, re.IGNORECASE)
    return m.group(1) if m else None


def ambil_ringkasan_bulletin_terbaru() -> dict:
    """
    Best-effort. Return dict berisi periode/url_sumber/musim_panen dan lima
    angka (produksi, grindings, stok, surplus/defisit, rasio stok-grindings)
    -- field yang gagal di-parse bernilai None, TIDAK PERNAH menebak.

    Melempar ValueError kalau bulletin terbaru tidak ditemukan sama sekali,
    atau kalau tidak ada satupun angka yang berhasil diambil (supaya caller
    tahu ini gagal total, bukan cuma parsial) -- caller (dashboard) menangkap
    ini dan mengarahkan pengguna ke pengisian manual, tidak pernah crash.
    """
    session = requests.Session()
    url = _url_bulletin_terbaru(session)
    periode = _periode_dari_url(url)

    r = session.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    teks = _bersihkan_html(r.text)

    produksi_pct, produksi = _cari_naik_turun(teks, r"World\s+(?:Gross\s+)?Production")
    grindings_pct, grindings = _cari_naik_turun(teks, r"World\s+Grindings")
    if produksi is None or grindings is None:
        p2, g2 = _cari_gabungan_produksi_grindings(teks)
        produksi = produksi if produksi is not None else p2
        grindings = grindings if grindings is not None else g2

    hasil = {
        "periode": periode,
        "url_sumber": url,
        "musim_panen": _cari_musim(teks),
        "produksi_ribu_ton": produksi,
        "produksi_pct_yoy": produksi_pct,
        "grindings_ribu_ton": grindings,
        "grindings_pct_yoy": grindings_pct,
        "stok_ribu_ton": _cari_stok(teks),
        "surplus_defisit_ribu_ton": _cari_surplus_defisit(teks),
        "rasio_stok_grindings_pct": _cari_rasio(teks),
    }

    angka_didapat = [v for k, v in hasil.items() if k not in ("periode", "url_sumber", "musim_panen")]
    if all(v is None for v in angka_didapat):
        raise ValueError(
            "Tidak ada satupun angka yang berhasil di-parse dari siaran pers ICCO "
            "terbaru -- kemungkinan redaksi kalimat berubah lagi. Isi manual dari "
            "teks bulletin: " + url
        )
    return hasil
