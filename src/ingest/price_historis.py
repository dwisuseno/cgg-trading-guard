# src/ingest/price_historis.py
"""
Harga bulanan HISTORIS resmi ICCO (icco.org/statistics) -- bukan API resmi,
tapi tabel statistik publik yang mereka publikasikan gratis di halaman itu
(berbeda dari Quarterly Bulletin/Monthly Report yang berbayar, lihat
spesifikasi 3.1). Diambil dua langkah, keduanya http polos tanpa browser:

  1. GET halaman statistik -> ambil nonce sekali-pakai per tabel
     (wdtNonceFrontendServerSide_6, tertanam di HTML server-side).
  2. POST ke admin-ajax.php (plugin wpDataTables mereka) dengan nonce itu
     -> dapat seluruh baris tabel "Monthly average prices" (Euro/tonne dan
     US$/tonne), sejak Januari 2005.

Dites manual 2026-09-07: 262 baris kembali dalam satu request. Kalau ICCO
mengubah struktur halaman/plugin, fungsi ini akan gagal dengan jelas
(exception) -- dashboard menangkapnya dan tetap jalan dengan data yang
sudah tersimpan, tidak pernah membuat aplikasi crash.
"""
import re
from datetime import datetime

import requests

ICCO_STATS_URL = "https://www.icco.org/statistics/"
ICCO_AJAX_URL = "https://www.icco.org/wp-admin/admin-ajax.php"
ICCO_TABLE_ID = "6"  # tabel "Monthly average prices" di halaman statistik
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CGGTradingGuard/1.0; +internal decision-support tool)"}


def _ambil_nonce(session: requests.Session) -> str:
    r = session.get(ICCO_STATS_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    m = re.search(
        rf'wdtNonceFrontendServerSide_{ICCO_TABLE_ID}[^>]*value="([a-f0-9]+)"',
        r.text,
    )
    if not m:
        raise ValueError(
            "Nonce tabel ICCO tidak ditemukan -- kemungkinan struktur halaman berubah."
        )
    return m.group(1)


def ambil_historis_bulanan_icco() -> list[dict]:
    """
    Return list of {"periode": "YYYY-MM", "index_eur_ton": float, "index_usd_ton": float},
    terurut lama -> baru. Melempar exception kalau gagal (caller yang menangani
    fallback -- lihat scheduler.ingest_historis_icco).
    """
    session = requests.Session()
    nonce = _ambil_nonce(session)

    data = {
        "draw": "1", "start": "0", "length": "1000",
        "order[0][column]": "1", "order[0][dir]": "asc",
        "search[value]": "", "search[regex]": "false",
        "wdtNonce": nonce, "sRangeSeparator": "|",
    }
    kolom = [("0", "wdt_ID"), ("1", "month"), ("2", "sdrstonne"), ("3", "ustonne")]
    for i, (idx, nama) in enumerate(kolom):
        data[f"columns[{i}][data]"] = idx
        data[f"columns[{i}][name]"] = nama
        data[f"columns[{i}][searchable]"] = "true"
        data[f"columns[{i}][orderable]"] = "true"
        data[f"columns[{i}][search][value]"] = "|" if nama == "month" else ""
        data[f"columns[{i}][search][regex]"] = "false"

    r = session.post(
        f"{ICCO_AJAX_URL}?action=get_wdtable&table_id={ICCO_TABLE_ID}",
        data=data,
        headers={**HEADERS, "X-Requested-With": "XMLHttpRequest", "Referer": ICCO_STATS_URL},
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()

    hasil = []
    for row in payload.get("data", []):
        try:
            _id, tanggal_str, eur_str, usd_str = row
            if not tanggal_str:
                continue  # baris kosong yang kadang ada di data sumber
            tgl = datetime.strptime(tanggal_str, "%d/%m/%Y")
            hasil.append({
                "periode": tgl.strftime("%Y-%m"),
                "index_eur_ton": float(eur_str.replace(",", "")),
                "index_usd_ton": float(usd_str.replace(",", "")),
            })
        except (ValueError, TypeError):
            continue  # lewati baris yang tidak bisa diparse, jangan gagal total
    hasil.sort(key=lambda x: x["periode"])
    return hasil
