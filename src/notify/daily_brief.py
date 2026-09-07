# src/notify/daily_brief.py
"""
Daily Brief — format WhatsApp, sengaja pendek. Lihat Spesifikasi Sistem
bagian 8. Modul ini HANYA menyusun teksnya; pengiriman aktual (WhatsApp
Business API / email) belum dihubungkan -- butuh kredensial & izin eksplisit
dari pemilik akun, di luar cakupan yang bisa diaktifkan dari sini.
"""
from datetime import date

HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BULAN = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def _tgl_pendek(d: date) -> str:
    return f"{HARI[d.weekday()]}, {d.day} {BULAN[d.month]} {d.year}"


def susun_brief(
    tanggal: date,
    harga: dict,
    climate: dict,
    cuaca: dict,          # {"BRU-01": {...}, "SUL-01": {...}}
    buy_guard_rows: list, # list of dict dari db.buy_guard_today, skenario=konservatif
    posisi_stok: dict,    # {"total_kg": ..., "umur_rata_hari": ..., "sinyal": ...}
    alerts: list,
    nama_titik: dict,     # {"BRU-01": "Berau", "SUL-01": "Sulawesi"}
    musim: dict | None = None,        # dari engine.musiman.fase_panen_lokal()
    cuaca_global: dict | None = None, # {"CIV-01": {...}, "GHA-01": {...}}
) -> str:
    idx = harga.get("index_idr_per_kg")
    idx_txt = f"{idx:,.0f}".replace(",", ".") if idx else "—"
    kurs = harga.get("kurs_usd_idr")
    kurs_txt = f"{kurs:,.0f}".replace(",", ".") if kurs else "—"
    stale = " (BASI — mohon perbarui)" if harga.get("stale") else ""

    oni = climate.get("oni") if climate else None
    fase = climate.get("fase") if climate else None
    oni_txt = f"{oni:+.2f}" if oni is not None else "—"
    fase_txt = {"el_nino": "El Nino", "la_nina": "La Nina", "netral": "Netral"}.get(fase, "—")

    baris_cuaca = []
    for kode, nama in nama_titik.items():
        c = cuaca.get(kode) or {}
        baris_cuaca.append(
            f"{nama:<9}: {c.get('hujan_14hari_mm', '—')}mm — risiko proses {c.get('risiko_proses', '—')}"
        )

    # ambil skenario konservatif per grade untuk titik pertama yang ada datanya
    grid = {}
    for row in buy_guard_rows:
        if row["skenario"] != "konservatif":
            continue
        grid[row["grade"]] = (row["harga_maks_basah"], row["harga_maks_kering"])

    def fmt(v):
        return f"{v:,.0f}".replace(",", ".") if v is not None else "—"

    baris_harga = []
    for grade_label, key in (("Premium", "premium"), ("Medium", "medium"), ("Low", "low")):
        basah, kering = grid.get(key, (None, None))
        baris_harga.append(f"{grade_label:<7} {fmt(basah):>8}     {fmt(kering):>8}")

    alert_txt = "\n".join(f"• {a}" for a in alerts) if alerts else "• Tidak ada alert hari ini"

    musim = musim or {}
    baris_musim = ""
    if musim:
        baris_musim = (
            f"\n📅 MUSIM ({musim.get('label', '—')})\n"
            f"Dampak: {musim.get('dampak', '—')}\n"
            f"Antisipasi: {musim.get('antisipasi', '—')}\n"
        )

    baris_global_txt = ""
    if cuaca_global:
        baris_global = []
        for kode, c in cuaca_global.items():
            c = c or {}
            baris_global.append(
                f"{kode:<7}: {c.get('hujan_14hari_mm', '—')}mm — risiko proses {c.get('risiko_proses', '—')}"
            )
        if baris_global:
            baris_global_txt = (
                "\n🌍 IKLIM SABUK PRODUSEN (Afrika Barat — sinyal index dunia)\n"
                + chr(10).join(baris_global) + "\n"
            )

    return f"""🌱 CGG TRADING GUARD — {_tgl_pendek(tanggal)}

📊 PASAR
Index: Rp{idx_txt}/kg kering-setara{stale}
Kurs : Rp{kurs_txt}/USD

🌊 IKLIM
ONI {oni_txt} ({fase_txt})

🌧️ CUACA 14 HARI (lokal — risiko proses)
{chr(10).join(baris_cuaca)}
{baris_global_txt}{baris_musim}
💰 HARGA BELI MAKS HARI INI — KONSERVATIF (Rp/kg)
        BASAH        KERING
{chr(10).join(baris_harga)}
⚠️ Pegang angka di atas. Lebih tinggi = wajib alasan.

📦 POSISI STOK
Total {posisi_stok.get('total_kg', '—')}kg · umur rata-rata {posisi_stok.get('umur_rata_hari', '—')} hari
Sinyal: {posisi_stok.get('sinyal', '—')}

🔔 ALERT
{alert_txt}
"""
