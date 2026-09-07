# dashboard/app.py
"""
Dashboard CGG Trading Guard (Streamlit). Jalankan dari root proyek:
    streamlit run dashboard/app.py
"""
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from src import db, scheduler
from src.ingest import price

st.set_page_config(page_title="CGG Trading Guard", page_icon="🌱", layout="wide")
db.init_db()
cfg = scheduler.load_config()

st.title("🌱 CGG Trading Guard")
st.caption("Sistem pendukung keputusan beli & jual kakao — bukan sistem prediksi harga.")

if cfg["meta"]["status"] != "TERVALIDASI":
    st.warning(
        f"⚠️ Parameter versi **{cfg['meta']['versi']}** berstatus **{cfg['meta']['status']}**. "
        "Sebagian angka biaya/overhead masih placeholder 0 — lihat `config/parameters.yaml` "
        "dan bagian 11 spesifikasi (tujuh angka yang wajib dikonfirmasi) sebelum dipakai untuk "
        "keputusan pembelian/penjualan nyata."
    )

tab_beli, tab_jual, tab_data, tab_input = st.tabs(
    ["💰 Buy Guard", "📦 Sell Guard", "📊 Data Pasar & Iklim", "✍️ Input Manual"]
)

with db.get_connection() as conn:
    harga = db.latest_market_price(conn)
    clim = db.latest_climate(conn)
    cuaca_per_titik = {t["kode"]: db.latest_weather(conn, t["kode"]) for t in cfg["titik_terima"]}
    rows_today = db.buy_guard_today(conn, date.today().isoformat())
    lots = db.open_lots(conn)

# ---------------- TAB: Buy Guard ----------------
with tab_beli:
    if not harga or not harga.get("index_idr_per_kg"):
        st.info("Belum ada harga index hari ini. Isi lewat tab **Input Manual** dulu, lalu tekan **Hitung Buy Guard** di bawah.")
    else:
        st.metric("Index harga (Rp/kg kering-setara)", f"Rp {harga['index_idr_per_kg']:,.0f}".replace(",", "."))

    if st.button("🔄 Ingest harga + hitung Buy Guard sekarang", key="run_buy"):
        with st.spinner("Menghitung..."):
            scheduler.hitung_buy_guard()
        st.rerun()

    if rows_today:
        df = pd.DataFrame(rows_today)
        for kode, nama in [(t["kode"], t["nama"]) for t in cfg["titik_terima"]]:
            sub = df[df["kode_titik"] == kode]
            if sub.empty:
                continue
            st.subheader(f"📍 {nama} ({kode})")
            basah = sub.pivot(index="grade", columns="skenario", values="harga_maks_basah")
            kering = sub.pivot(index="grade", columns="skenario", values="harga_maks_kering")
            cols = [c for c in ["konservatif", "basis", "optimis"] if c in basah.columns]
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Basah (Rp/kg)**")
                st.dataframe(basah[cols].style.format("{:,.0f}"), use_container_width=True)
            with c2:
                st.markdown("**Kering (Rp/kg)**")
                st.dataframe(kering[cols].style.format("{:,.0f}"), use_container_width=True)
        st.caption("⚠️ Pegang kolom **konservatif** di lapangan. Tawaran di atas **basis** wajib persetujuan koordinator + alasan tertulis.")
    else:
        st.caption("Belum ada hasil Buy Guard untuk hari ini.")

# ---------------- TAB: Sell Guard ----------------
with tab_jual:
    if st.button("🔄 Hitung Sell Guard sekarang", key="run_sell"):
        with st.spinner("Menghitung..."):
            hasil_sell = scheduler.hitung_sell_guard()
            st.session_state["sell_result"] = hasil_sell

    hasil_sell = st.session_state.get("sell_result")
    if not lots:
        st.info("Belum ada lot terbuka di `lot_realisasi` (tanggal_jual kosong). Tambahkan lot lewat tab **Input Manual**.")
    elif hasil_sell:
        for r in hasil_sell:
            warna = {"TAHAN": "success", "JUAL": "error", "ZONA ABU-ABU": "warning"}.get(r["sinyal"], "info")
            with st.container(border=True):
                st.markdown(f"**Lot {r['lot_id']}** — Sinyal: **{r['sinyal']}**")
                st.caption(r["alasan"])
                c1, c2, c3 = st.columns(3)
                c1.metric("Harga impas 1 bulan", f"Rp {r['harga_impas_1_bulan']:,.0f}".replace(",", "."))
                c2.metric("Margin jika jual sekarang", f"Rp {r['margin_jika_jual_sekarang']:,.0f}".replace(",", "."))
                c3.metric("Band 3 bulan", f"{r['band']['band_bawah']:,.0f} – {r['band']['band_atas']:,.0f}".replace(",", "."))
                if not r["band"]["data_cukup"]:
                    st.caption(f"ℹ️ {r['band']['catatan']}")
    else:
        st.caption("Tekan tombol di atas untuk menghitung sinyal jual/tahan lot terbuka.")

# ---------------- TAB: Data Pasar & Iklim ----------------
with tab_data:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Harga pasar")
        if harga:
            st.json({k: v for k, v in harga.items()})
        else:
            st.caption("Belum ada data.")
        st.subheader("Iklim (ONI)")
        if st.button("🔄 Ambil ONI terbaru (NOAA)"):
            with st.spinner("Mengambil data NOAA..."):
                try:
                    scheduler.ingest_oni()
                    st.success("Berhasil.")
                except Exception as e:
                    st.error(f"Gagal mengambil ONI: {e}")
            st.rerun()
        if clim:
            st.json({k: v for k, v in clim.items()})
        else:
            st.caption("Belum ada data.")
    with c2:
        st.subheader("Cuaca 14 hari (Open-Meteo)")
        if st.button("🔄 Ambil cuaca terbaru"):
            with st.spinner("Mengambil data Open-Meteo..."):
                try:
                    scheduler.ingest_cuaca()
                    st.success("Berhasil.")
                except Exception as e:
                    st.error(f"Gagal mengambil cuaca: {e}")
            st.rerun()
        for t in cfg["titik_terima"]:
            w = cuaca_per_titik.get(t["kode"])
            st.markdown(f"**{t['nama']}** ({t['kode']})")
            st.json(w if w else {"status": "belum ada data"})

    st.divider()
    st.subheader("📨 Daily Brief (pratinjau)")
    if st.button("Susun daily brief sekarang"):
        with st.spinner("Menyusun..."):
            teks = scheduler.kirim_daily_brief()
        st.code(teks, language=None)
        st.caption("Disimpan sebagai file `.txt` di folder `data/`. Pengiriman WhatsApp/email otomatis belum dihubungkan — butuh kredensial API dan izin eksplisit.")

# ---------------- TAB: Input Manual ----------------
with tab_input:
    st.subheader("Catat harga hari ini (Layer 3 — fallback yang selalu tersedia)")
    with st.form("form_harga"):
        c1, c2, c3 = st.columns(3)
        ny = c1.number_input("ICE New York (USD/ton)", min_value=0.0, step=10.0)
        ld = c2.number_input("ICE London (GBP/ton, opsional)", min_value=0.0, step=10.0)
        kurs = c3.number_input("Kurs USD/IDR (mis. JISDOR)", min_value=0.0, step=10.0, value=float(harga.get("kurs_usd_idr") or 0) if harga else 0.0)
        icco = st.number_input("Harga resmi ICCO hari ini (USD/ton, opsional — untuk kalibrasi)", min_value=0.0, step=10.0)
        submitted = st.form_submit_button("Simpan harga hari ini")
        if submitted:
            with db.get_connection() as conn:
                row = price.catat_harga_manual(
                    conn,
                    ice_ny_usd_ton=ny or None,
                    ice_london_gbp_ton=ld or None,
                    kurs_usd_idr=kurs or None,
                    icco_resmi_usd=icco or None,
                )
            st.success(f"Tersimpan: Rp {row['index_idr_per_kg']:,.0f}/kg".replace(",", ".") if row.get("index_idr_per_kg") else "Tersimpan (index belum lengkap — isi kurs & minimal satu harga futures).")
            st.rerun()

    st.divider()
    st.subheader("Tambah lot (untuk Sell Guard)")
    with st.form("form_lot"):
        c1, c2, c3 = st.columns(3)
        lot_id = c1.text_input("Lot ID", placeholder="mis. BRU-2026-09-001")
        berat = c2.number_input("Berat masuk (kg)", min_value=0.0, step=10.0)
        hpp = c3.number_input("HPP aktual (Rp/kg)", min_value=0.0, step=100.0)
        umur = st.number_input("Umur stok saat ini (hari)", min_value=0, step=1)
        submitted_lot = st.form_submit_button("Simpan lot")
        if submitted_lot and lot_id:
            with db.get_connection() as conn:
                db.upsert(conn, "lot_realisasi", {
                    "lot_id": lot_id,
                    "berat_masuk_kg": berat,
                    "berat_kering_kg": None,
                    "rendemen_aktual": None,
                    "rendemen_diasumsikan": cfg["rendemen"]["basah_ke_kering"]["basis"],
                    "metode_fermentasi": None,
                    "durasi_fermentasi_jam": None,
                    "bean_count": None,
                    "ka_pct": None,
                    "slaty_pct": None,
                    "grade_akhir": None,
                    "hpp_aktual_rp_kg": hpp or None,
                    "tanggal_jual": None,
                    "segmen_pembeli": None,
                    "harga_jual_rp_kg": None,
                    "margin_realisasi_rp_kg": None,
                    "umur_stok_hari": int(umur),
                })
            st.success(f"Lot {lot_id} tersimpan.")
            st.rerun()

st.divider()
st.caption(
    f"Versi parameter: {cfg['meta']['versi']} · Status: {cfg['meta']['status']} · "
    f"Terakhir diperbarui: {cfg['meta']['terakhir_diperbarui']}"
)
