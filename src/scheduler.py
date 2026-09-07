# src/scheduler.py
"""
Orkestrasi harian/bulanan. Lihat Spesifikasi Sistem bagian 7.5.

Menjalankan file ini secara langsung (`python -m src.scheduler`) memblokir
proses dan menjalankan job sesuai jadwal cron di bawah -- cocok dijalankan
sebagai proses latar belakang yang selalu menyala (mis. lewat Windows Task
Scheduler / NSSM), bukan dipanggil manual berulang kali.

Untuk uji coba satu siklus penuh tanpa menunggu jadwal, pakai run_once.py
di root proyek.
"""
import logging
import sys
from datetime import date, datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler

from . import db
from .ingest import price, climate, weather
from .engine import buy_guard, sell_guard, scenario
from .notify import daily_brief

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cgg-trading-guard")

CONFIG_PATH = db.BASE_DIR / "config" / "parameters.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ingest_harga():
    with db.get_connection() as conn:
        hasil = price.ambil_harga_hari_ini(conn)
        if hasil.get("status") == "KOSONG":
            log.warning(hasil["pesan"])
        elif hasil.get("stale"):
            log.warning("Harga hari ini memakai nilai fallback (basi) tanggal %s", hasil.get("tanggal"))
        else:
            log.info("Harga tersimpan: %s", hasil.get("tanggal"))
        return hasil


def ingest_cuaca():
    cfg = load_config()
    hasil = {}
    with db.get_connection() as conn:
        for titik in cfg["titik_terima"]:
            data = weather.ambil_cuaca(titik["lat"], titik["lon"])
            row = {
                "tanggal": date.today().isoformat(),
                "kode_titik": titik["kode"],
                "hujan_mm": data["hujan_hari_ini_mm"],
                "hujan_14hari_mm": data["hujan_14hari_mm"],
                "kelembapan_pct": data["kelembapan_pct"],
                "radiasi_mj": data["radiasi_mj"],
                "risiko_proses": data["risiko_proses"],
            }
            db.upsert(conn, "weather", row)
            hasil[titik["kode"]] = data
            log.info("Cuaca %s: hujan 14hr %.1fmm, risiko %s", titik["nama"], data["hujan_14hari_mm"], data["risiko_proses"])
    return hasil


def ingest_oni():
    hasil = climate.ambil_oni()
    periode = f"{hasil['tahun']}-{hasil['seas']}"
    with db.get_connection() as conn:
        db.upsert(conn, "climate", {
            "periode": periode,
            "oni": hasil["oni"],
            "fase": hasil["fase"],
            "diambil_pada": datetime.now().isoformat(timespec="seconds"),
        })
    log.info("ONI %s: %.2f (%s)", periode, hasil["oni"], hasil["fase"])
    return hasil


def hitung_buy_guard():
    cfg = load_config()
    tanggal = date.today().isoformat()
    with db.get_connection() as conn:
        harga = db.latest_market_price(conn)
        clim = db.latest_climate(conn)
        oni = clim["oni"] if clim else 0.0

        if not harga or not harga.get("index_idr_per_kg"):
            log.warning("Tidak ada index_idr_per_kg -- Buy Guard dilewati. Isi harga manual dulu.")
            return []

        semua = []
        for titik in cfg["titik_terima"]:
            hasil = buy_guard.hitung_semua_skenario(
                index_idr_per_kg=harga["index_idr_per_kg"],
                kode_titik=titik["kode"],
                cfg=cfg,
                oni=oni,
            )
            for h in hasil:
                row = {
                    "tanggal": tanggal,
                    "kode_titik": titik["kode"],
                    "grade": h.grade,
                    "skenario": h.skenario,
                    "harga_maks_basah": h.harga_maks_basah,
                    "harga_maks_kering": h.harga_maks_kering,
                    "versi_parameter": cfg["meta"]["versi"],
                }
                db.upsert(conn, "buy_guard_harian", row)
                semua.append(row)
        log.info("Buy Guard dihitung untuk %d titik terima.", len(cfg["titik_terima"]))
        return semua


def hitung_sell_guard():
    cfg = load_config()
    with db.get_connection() as conn:
        harga = db.latest_market_price(conn)
        clim = db.latest_climate(conn)
        oni = clim["oni"] if clim else 0.0
        if not harga or not harga.get("index_idr_per_kg"):
            log.warning("Tidak ada harga -- Sell Guard dilewati.")
            return []

        historis = [h["index_idr_per_kg"] for h in db.price_history(conn, cfg["band_skenario"]["jendela_volatilitas_hari"])]
        band = scenario.hitung_band(harga["index_idr_per_kg"], historis, oni, cfg)

        lots = db.open_lots(conn)
        hasil = []
        for lot in lots:
            if not lot.get("hpp_aktual_rp_kg"):
                continue
            sinyal = sell_guard.sinyal_jual_tahan(
                harga_jual_hari_ini=harga["index_idr_per_kg"],
                hpp_lot=lot["hpp_aktual_rp_kg"],
                band_bawah_3bln=band["band_bawah"],
                band_atas_3bln=band["band_atas"],
                cfg=cfg,
            )
            hasil.append({"lot_id": lot["lot_id"], **sinyal, "band": band})
        log.info("Sell Guard dihitung untuk %d lot terbuka.", len(hasil))
        return hasil


def cek_alert():
    with db.get_connection() as conn:
        lots = db.open_lots(conn)
        semua = []
        for lot in lots:
            semua.extend(sell_guard.alert_untuk_lot(lot))
        for a in semua:
            log.warning("ALERT: %s", a)
        return semua


def kirim_daily_brief():
    """Menyusun & mencetak brief. Pengiriman WA/email nyata BELUM dihubungkan
    (butuh kredensial + izin eksplisit pemilik akun)."""
    cfg = load_config()
    tanggal = date.today()
    with db.get_connection() as conn:
        harga = db.latest_market_price(conn) or {}
        clim = db.latest_climate(conn) or {}
        cuaca = {t["kode"]: db.latest_weather(conn, t["kode"]) or {} for t in cfg["titik_terima"]}
        rows = db.buy_guard_today(conn, tanggal.isoformat())
        lots = db.open_lots(conn)
        posisi = {
            "total_kg": round(sum(l.get("berat_masuk_kg") or 0 for l in lots)),
            "umur_rata_hari": (
                round(sum(l.get("umur_stok_hari") or 0 for l in lots) / len(lots))
                if lots else 0
            ),
            "sinyal": "Lihat dashboard" if lots else "Belum ada lot terbuka",
        }
        alerts = cek_alert()
        nama_titik = {t["kode"]: t["nama"] for t in cfg["titik_terima"]}

        teks = daily_brief.susun_brief(
            tanggal=tanggal, harga=harga, climate=clim, cuaca=cuaca,
            buy_guard_rows=rows, posisi_stok=posisi, alerts=alerts, nama_titik=nama_titik,
        )
        print(teks)
        out_path = db.BASE_DIR / "data" / f"brief-{tanggal.isoformat()}.txt"
        out_path.write_text(teks, encoding="utf-8")
        log.info("Brief disimpan ke %s (pengiriman WA/email belum dihubungkan)", out_path)
        return teks


def laporan_kalibrasi():
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT rendemen_aktual, rendemen_diasumsikan FROM lot_realisasi "
            "WHERE rendemen_aktual IS NOT NULL"
        ).fetchall()
    if not rows:
        log.info("Belum ada lot_realisasi untuk kalibrasi.")
        return None
    deviasi = [abs(r["rendemen_aktual"] - r["rendemen_diasumsikan"]) for r in rows if r["rendemen_diasumsikan"]]
    rata = sum(deviasi) / len(deviasi) if deviasi else None
    log.info("Kalibrasi rendemen: rata-rata deviasi %.3f dari %d lot", rata or 0, len(rows))
    return rata


def pagi():
    """Sebelum crew turun ke lapangan."""
    ingest_harga()
    ingest_cuaca()
    hitung_buy_guard()
    kirim_daily_brief()


def sore():
    """Setelah penutupan London."""
    ingest_harga()
    hitung_sell_guard()
    cek_alert()


def bulanan():
    ingest_oni()
    laporan_kalibrasi()


def main():
    db.init_db()
    sched = BlockingScheduler(timezone="Asia/Makassar")
    sched.add_job(pagi, "cron", hour=6, minute=0, id="pagi")
    sched.add_job(sore, "cron", hour=17, minute=0, id="sore")
    sched.add_job(bulanan, "cron", day=8, hour=7, id="bulanan")
    log.info("Scheduler dimulai. Job: pagi 06:00, sore 17:00, bulanan tgl 8 jam 07:00 (Asia/Makassar).")
    sched.start()


if __name__ == "__main__":
    main()
