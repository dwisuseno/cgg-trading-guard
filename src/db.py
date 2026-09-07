"""
Lapisan penyimpanan — satu file SQLite, tanpa server database.
Skema persis sesuai Spesifikasi Sistem CGG Trading Guard, bagian 6.
"""
import sqlite3
from pathlib import Path
from contextlib import contextmanager

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "cgg.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS market_price (
  tanggal            DATE PRIMARY KEY,
  ice_ny_usd_ton     REAL,
  ice_london_gbp_ton REAL,
  index_rekonstruksi_usd REAL,
  icco_resmi_usd     REAL,
  deviasi_pct        REAL,
  kurs_usd_idr       REAL,
  index_idr_per_kg   REAL,
  sumber             TEXT,
  diambil_pada       TIMESTAMP
);

CREATE TABLE IF NOT EXISTS market_price_historis_bulanan (
  periode         TEXT PRIMARY KEY,  -- 'YYYY-MM'
  index_eur_ton   REAL,
  index_usd_ton   REAL,
  sumber          TEXT,
  diambil_pada    TIMESTAMP
);

CREATE TABLE IF NOT EXISTS climate (
  periode      TEXT PRIMARY KEY,
  oni          REAL,
  fase         TEXT,
  diambil_pada TIMESTAMP
);

CREATE TABLE IF NOT EXISTS weather (
  tanggal          DATE,
  kode_titik       TEXT,
  hujan_mm         REAL,
  hujan_14hari_mm  REAL,
  kelembapan_pct   REAL,
  radiasi_mj       REAL,
  risiko_proses    TEXT,
  PRIMARY KEY (tanggal, kode_titik)
);

CREATE TABLE IF NOT EXISTS buy_guard_harian (
  tanggal            DATE,
  kode_titik         TEXT,
  grade              TEXT,
  skenario           TEXT,
  harga_maks_basah   REAL,
  harga_maks_kering  REAL,
  versi_parameter    TEXT,
  PRIMARY KEY (tanggal, kode_titik, grade, skenario)
);

CREATE TABLE IF NOT EXISTS transaksi_beli (
  lot_id             TEXT PRIMARY KEY,
  tanggal            DATE,
  kode_titik         TEXT,
  id_petani          TEXT,
  bentuk             TEXT,
  grade_intake       TEXT,
  berat_kg           REAL,
  harga_aktual_rp_kg REAL,
  harga_maks_sistem  REAL,
  deviasi_rp_kg      REAL,
  alasan_override    TEXT,
  dicatat_oleh       TEXT
);

CREATE TABLE IF NOT EXISTS lot_realisasi (
  lot_id                TEXT PRIMARY KEY,
  berat_masuk_kg        REAL,
  berat_kering_kg       REAL,
  rendemen_aktual       REAL,
  rendemen_diasumsikan  REAL,
  metode_fermentasi     TEXT,
  durasi_fermentasi_jam INTEGER,
  bean_count            INTEGER,
  ka_pct                REAL,
  slaty_pct             REAL,
  grade_akhir           TEXT,
  hpp_aktual_rp_kg      REAL,
  tanggal_jual          DATE,
  segmen_pembeli        TEXT,
  harga_jual_rp_kg      REAL,
  margin_realisasi_rp_kg REAL,
  umur_stok_hari        INTEGER
);
"""


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript(SCHEMA)
    return DB_PATH


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert(conn, table: str, row: dict):
    cols = ", ".join(row.keys())
    placeholders = ", ".join("?" * len(row))
    updates = ", ".join(f"{k}=excluded.{k}" for k in row.keys())
    sql = (
        f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT DO UPDATE SET {updates}"
    )
    conn.execute(sql, list(row.values()))


def latest_market_price(conn):
    row = conn.execute(
        "SELECT * FROM market_price ORDER BY tanggal DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def price_history(conn, hari: int = 90):
    rows = conn.execute(
        "SELECT tanggal, index_idr_per_kg FROM market_price "
        "WHERE index_idr_per_kg IS NOT NULL "
        "ORDER BY tanggal DESC LIMIT ?",
        (hari,),
    ).fetchall()
    return [dict(r) for r in rows]


def historis_bulanan(conn, tahun: int | None = None):
    """Seri bulanan lengkap (atau N tahun terakhir), lama -> baru, untuk grafik tren."""
    if tahun:
        rows = conn.execute(
            "SELECT * FROM market_price_historis_bulanan "
            "WHERE periode >= date('now', ?) "
            "ORDER BY periode ASC",
            (f"-{tahun} years",),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM market_price_historis_bulanan ORDER BY periode ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def latest_climate(conn):
    row = conn.execute(
        "SELECT * FROM climate ORDER BY periode DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def latest_weather(conn, kode_titik: str):
    row = conn.execute(
        "SELECT * FROM weather WHERE kode_titik = ? ORDER BY tanggal DESC LIMIT 1",
        (kode_titik,),
    ).fetchone()
    return dict(row) if row else None


def buy_guard_today(conn, tanggal: str):
    rows = conn.execute(
        "SELECT * FROM buy_guard_harian WHERE tanggal = ? "
        "ORDER BY kode_titik, grade, skenario",
        (tanggal,),
    ).fetchall()
    return [dict(r) for r in rows]


def open_lots(conn):
    rows = conn.execute(
        "SELECT * FROM lot_realisasi WHERE tanggal_jual IS NULL"
    ).fetchall()
    return [dict(r) for r in rows]
