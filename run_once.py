"""
Menjalankan satu siklus penuh secara manual, tanpa menunggu jadwal cron —
untuk uji coba/demo. Setara dengan job `pagi()` + `sore()` di scheduler.py.

Pakai:
    python run_once.py
"""
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from src import db
from src.scheduler import (
    ingest_harga, ingest_cuaca, ingest_cuaca_global, ingest_oni, ingest_historis_icco,
    hitung_buy_guard, hitung_sell_guard, kirim_daily_brief,
)


def main():
    path = db.init_db()
    print(f"[1/7] Database siap: {path}")

    print("[2/7] Mengambil ONI (NOAA)...")
    try:
        oni = ingest_oni()
        print(f"      ONI = {oni['oni']:+.2f} ({oni['fase']})")
    except Exception as e:
        print(f"      GAGAL ambil ONI: {e}")

    print("[3/7] Mengambil cuaca 14 hari (Open-Meteo) untuk semua titik terima (lokal + global)...")
    try:
        cuaca = ingest_cuaca()
        for kode, d in cuaca.items():
            print(f"      {kode}: hujan14hr={d['hujan_14hari_mm']}mm risiko={d['risiko_proses']}")
    except Exception as e:
        print(f"      GAGAL ambil cuaca lokal: {e}")
    try:
        cuaca_global = ingest_cuaca_global()
        for kode, d in cuaca_global.items():
            print(f"      {kode} (global): hujan14hr={d['hujan_14hari_mm']}mm risiko={d['risiko_proses']}")
    except Exception as e:
        print(f"      GAGAL ambil cuaca global: {e}")

    print("[4/7] Mengecek harga index...")
    hasil_harga = ingest_harga()
    if hasil_harga.get("status") == "KOSONG":
        print("      Belum ada harga tersimpan. Contoh cara mengisi manual:")
        print("      >>> from src import db")
        print("      >>> from src.ingest import price")
        print("      >>> with db.get_connection() as conn:")
        print("      ...     price.catat_harga_manual(conn, ice_ny_usd_ton=8500, kurs_usd_idr=16300)")
        print("      Atau isi lewat dashboard (tab 'Input Manual').")
    else:
        print(f"      Harga index_idr_per_kg: {hasil_harga.get('index_idr_per_kg')} (sumber={hasil_harga.get('sumber')})")

    print("[5/7] Mengambil historis bulanan ICCO (icco.org/statistics)...")
    try:
        historis = ingest_historis_icco()
        print(f"      {len(historis)} bulan tersimpan ({historis[0]['periode']} .. {historis[-1]['periode']})")
    except Exception as e:
        print(f"      GAGAL ambil historis ICCO: {e}")

    print("[6/7] Menghitung Buy Guard & Sell Guard...")
    hitung_buy_guard()
    hitung_sell_guard()

    print("[7/7] Menyusun Daily Brief...")
    kirim_daily_brief()

    print("\nSelesai. Jalankan dashboard untuk lihat semuanya secara visual:")
    print("    streamlit run dashboard/app.py")


if __name__ == "__main__":
    main()
