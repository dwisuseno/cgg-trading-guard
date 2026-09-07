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
import plotly.graph_objects as go
import streamlit as st

from src import db, scheduler
from src.ingest import price
from src.notify import email_sender
from src.engine import musiman, anomali, korelasi

st.set_page_config(page_title="CGG Trading Guard", page_icon="🌱", layout="wide")
db.init_db()
cfg = scheduler.load_config()

_WARNA_RISIKO = {"rendah": "#5FA331", "sedang": "#E8A33D", "tinggi": "#D64545"}


def _kartu_cuaca(nama: str, w: dict | None):
    """Kartu cuaca ringkas (bukan st.json mentah) -- dipakai untuk titik lokal & global."""
    if not w:
        st.markdown(f"**{nama}**")
        st.caption("Belum ada data.")
        return
    warna = _WARNA_RISIKO.get(w.get("risiko_proses"), "#6B7A8C")
    with st.container(border=True):
        st.markdown(f"**{nama}**")
        c1, c2 = st.columns([2, 1])
        c1.metric("Hujan 14 hari", f"{w.get('hujan_14hari_mm', '—')}mm")
        with c2:
            st.markdown(
                f"<div style='margin-top:8px'><span style='background:{warna};color:white;"
                f"padding:3px 10px;border-radius:12px;font-size:12.5px;font-weight:600;'>"
                f"{(w.get('risiko_proses') or '—').upper()}</span></div>",
                unsafe_allow_html=True,
            )
        st.caption(f"Kelembapan {w.get('kelembapan_pct', '—')}% · {w.get('tanggal', '—')}")

st.title("🌱 CGG Trading Guard")
st.caption("Sistem pendukung keputusan beli & jual kakao — bukan sistem prediksi harga.")

if cfg["meta"]["status"] != "TERVALIDASI":
    st.warning(
        f"⚠️ Parameter versi **{cfg['meta']['versi']}** berstatus **{cfg['meta']['status']}**. "
        "Sebagian angka biaya/overhead masih placeholder 0 — lihat `config/parameters.yaml` "
        "dan bagian 11 spesifikasi (tujuh angka yang wajib dikonfirmasi) sebelum dipakai untuk "
        "keputusan pembelian/penjualan nyata."
    )


# ---------------- Auto-bootstrap: sekali per sesi, isi data hari ini kalau kosong ----------------
# Streamlit Cloud tidak menjalankan scheduler.py di latar belakang (lihat README) --
# jadi dashboard sendiri yang menutup celah itu: begitu ada orang membuka halaman
# ini, ia mengecek data hari ini dan menariknya kalau belum ada, meniru job `pagi()`
# tanpa perlu proses cron terpisah -- termasuk harga (Yahoo Finance + kurs, lihat
# src/ingest/price.py), yang sejak 2026-09 sudah otomatis dan tidak wajib diisi
# manual lagi. Input manual tetap ada sebagai override/fallback kalau fetch-nya gagal.
if not st.session_state.get("bootstrapped_today") == date.today().isoformat():
    with st.spinner("Menyiapkan data hari ini (harga, iklim, cuaca)..."):
        with db.get_connection() as _conn:
            _harga_ada = db.latest_market_price(_conn)
            _need_harga = not _harga_ada or _harga_ada.get("tanggal") != date.today().isoformat()
            _clim = db.latest_climate(_conn)
            _need_climate = not _clim or _clim.get("periode", "")[:4] != str(date.today().year)
            _need_weather = any(
                (db.latest_weather(_conn, t["kode"]) or {}).get("tanggal") != date.today().isoformat()
                for t in cfg["titik_terima"]
            )
            _need_weather_global = any(
                (db.latest_weather(_conn, t["kode"]) or {}).get("tanggal") != date.today().isoformat()
                for t in cfg.get("titik_pantau_global", [])
            )
            _hist_ada = db.historis_bulanan(_conn)
            _bulan_ini = date.today().strftime("%Y-%m")
            _need_historis = not _hist_ada or _hist_ada[-1]["periode"] != _bulan_ini
            # ONI & curah hujan historis jarang berubah drastis -- cukup tarik SEKALI
            # (bukan tiap bulan seperti ICCO) supaya bootstrap harian tetap ringan.
            _need_oni_historis = not db.oni_historis_bulanan(_conn)
            _need_hujan_historis = not db.cuaca_historis_bulanan(_conn, cfg.get("titik_pantau_global", [{}])[0].get("kode", ""))
        if _need_harga:
            try:
                scheduler.ingest_harga()
            except Exception as e:
                st.toast(f"Gagal auto-ambil harga: {e}", icon="⚠️")
        if _need_climate:
            try:
                scheduler.ingest_oni()
            except Exception as e:
                st.toast(f"Gagal auto-ambil ONI: {e}", icon="⚠️")
        if _need_weather:
            try:
                scheduler.ingest_cuaca()
            except Exception as e:
                st.toast(f"Gagal auto-ambil cuaca: {e}", icon="⚠️")
        if _need_weather_global:
            try:
                scheduler.ingest_cuaca_global()
            except Exception as e:
                st.toast(f"Gagal auto-ambil cuaca global: {e}", icon="⚠️")
        if _need_historis:
            try:
                scheduler.ingest_historis_icco()
            except Exception as e:
                st.toast(f"Gagal auto-ambil historis ICCO: {e}", icon="⚠️")
        if _need_oni_historis:
            try:
                scheduler.ingest_historis_oni()
            except Exception as e:
                st.toast(f"Gagal auto-ambil historis ONI: {e}", icon="⚠️")
        if _need_hujan_historis:
            try:
                scheduler.ingest_historis_cuaca_global_bulanan()
            except Exception as e:
                st.toast(f"Gagal auto-ambil historis curah hujan: {e}", icon="⚠️")
        # Buy Guard ikut dihitung ulang otomatis kalau harga hari ini sudah ada
        with db.get_connection() as _conn:
            _harga = db.latest_market_price(_conn)
        if _harga and _harga.get("index_idr_per_kg") and _harga.get("tanggal") == date.today().isoformat():
            try:
                scheduler.hitung_buy_guard()
            except Exception as e:
                st.toast(f"Gagal auto-hitung Buy Guard: {e}", icon="⚠️")
    st.session_state["bootstrapped_today"] = date.today().isoformat()

# Navigasi pakai segmented_control (bukan st.tabs) supaya pilihan tab TIDAK
# reset ke awal tiap ada interaksi lain di halaman (mis. klik tombol) --
# st.tabs() murni tampilan, tidak menyimpan state; ini penting untuk demo
# live supaya presenter tidak "terlempar" balik ke tab pertama tanpa sengaja.
NAV_OPTIONS = ["💰 Buy Guard", "📊 Data Pasar & Iklim", "📦 Sell Guard", "⚙️ Parameter (7 Angka)", "✍️ Input Manual"]

nav_col, refresh_col = st.columns([5, 1.7])
with nav_col:
    # st.radio(horizontal=True) dipakai, BUKAN st.segmented_control -- yang
    # terakhir itu dites dan ternyata tidak konsisten menjaga state-nya
    # sendiri lintas rerun (kadang lompat balik ke opsi lain begitu widget
    # LAIN di halaman dipencet), meski key+default sudah benar. st.radio
    # jauh lebih lawas dan battle-tested untuk pola stateful seperti ini --
    # penting untuk demo live yang tidak boleh "melompat" sendiri.
    nav = st.radio(
        "Navigasi", NAV_OPTIONS, horizontal=True, label_visibility="collapsed", key="nav"
    )
with refresh_col:
    if st.button("🔄 Refresh Semua Data", type="primary", width="stretch", key="refresh_all"):
        with st.spinner("Mengambil harga, iklim, cuaca lokal+global, dan historis ICCO..."):
            for _fn in (scheduler.ingest_harga, scheduler.ingest_oni, scheduler.ingest_cuaca,
                        scheduler.ingest_cuaca_global, scheduler.ingest_historis_icco):
                try:
                    _fn()
                except Exception as e:
                    st.toast(f"{_fn.__name__} gagal: {e}", icon="⚠️")
            try:
                scheduler.hitung_buy_guard()
            except Exception as e:
                st.toast(f"Hitung Buy Guard gagal: {e}", icon="⚠️")
        st.success("Semua data diperbarui.")
        st.rerun()

with db.get_connection() as conn:
    harga = db.latest_market_price(conn)
    clim = db.latest_climate(conn)
    cuaca_per_titik = {t["kode"]: db.latest_weather(conn, t["kode"]) for t in cfg["titik_terima"]}
    cuaca_global_per_titik = {t["kode"]: db.latest_weather(conn, t["kode"]) for t in cfg.get("titik_pantau_global", [])}
    rows_today = db.buy_guard_today(conn, date.today().isoformat())
    lots = db.open_lots(conn)

musim_ini = musiman.fase_panen_lokal(cfg)

# ---------------- TAB: Buy Guard ----------------
if nav == "💰 Buy Guard":
    st.caption(
        "Struktur biaya: Harga Jual = **Biaya Pokok Produksi (Raw Material — angka di "
        "bawah ini)** + Overhead Cost + Other Cost + Margin. Ubah tiga komponen terakhir "
        "di tab **⚙️ Parameter (7 Angka)**."
    )

    with st.container(border=True):
        c1, c2 = st.columns([1, 3])
        with c1:
            st.caption("📅 Musim")
            st.markdown(f"### {musim_ini['label']}")
        with c2:
            st.markdown(f"**Dampak:** {musim_ini['dampak']}")
            st.markdown(f"**Antisipasi:** {musim_ini['antisipasi']}")
        st.caption(
            "Catatan kualitatif dari kalender panen (edit di tab ⚙️ Parameter) — "
            "belum mengubah angka Buy Guard secara otomatis, lihat penjelasan di sana."
        )

    if not harga or not harga.get("index_idr_per_kg"):
        st.info("Belum ada harga index hari ini — tekan tombol di bawah untuk ambil otomatis, atau isi manual lewat tab **Input Manual**.")
    else:
        sumber_txt = harga.get("sumber", "")
        label_sumber = " (fallback/basi)" if harga.get("stale") else (" (otomatis)" if "otomatis" in sumber_txt else " (manual)")
        st.metric("Index harga (Rp/kg kering-setara)", f"Rp {harga['index_idr_per_kg']:,.0f}".replace(",", "."))
        st.caption(f"Sumber: {sumber_txt or '—'}{label_sumber} · tanggal {harga.get('tanggal', '—')}")

    if st.button("🔄 Ingest harga + hitung Buy Guard sekarang", key="run_buy"):
        with st.spinner("Mengambil harga & menghitung..."):
            scheduler.ingest_harga()
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
                st.dataframe(basah[cols].style.format("{:,.0f}"), width="stretch")
            with c2:
                st.markdown("**Kering (Rp/kg)**")
                st.dataframe(kering[cols].style.format("{:,.0f}"), width="stretch")
        st.caption("⚠️ Pegang kolom **konservatif** di lapangan. Tawaran di atas **basis** wajib persetujuan koordinator + alasan tertulis.")
    else:
        st.caption("Belum ada hasil Buy Guard untuk hari ini.")

# ---------------- TAB: Sell Guard ----------------
if nav == "📦 Sell Guard":
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
if nav == "📊 Data Pasar & Iklim":
    st.subheader("📈 Tren Harga ICCO — Bulanan")
    st.caption(
        "Sumber: tabel statistik resmi ICCO (icco.org/statistics), rata-rata bulanan "
        "sejak Januari 2005 — bukan Yahoo Finance proxy yang dipakai untuk harga harian "
        "di tab lain."
    )

    with db.get_connection() as conn:
        seri_historis = db.historis_bulanan(conn)
        oni_historis = db.oni_historis_bulanan(conn)
        hujan_historis = {
            t["kode"]: db.cuaca_historis_bulanan(conn, t["kode"])
            for t in cfg.get("titik_pantau_global", [])
        }

    hb1, hb2, hb3 = st.columns([1.3, 1.3, 2.4])
    with hb1:
        if st.button("🔄 Perbarui harga ICCO"):
            with st.spinner("Mengambil dari icco.org (bisa 10-20 detik)..."):
                try:
                    scheduler.ingest_historis_icco()
                    st.success("Berhasil.")
                except Exception as e:
                    st.error(f"Gagal mengambil data ICCO: {e}")
            st.rerun()
    with hb2:
        if st.button("🔄 Perbarui iklim historis"):
            with st.spinner("Mengambil ONI (NOAA) + curah hujan 20 tahun (Open-Meteo Archive)..."):
                try:
                    scheduler.ingest_historis_oni()
                    scheduler.ingest_historis_cuaca_global_bulanan()
                    st.success("Berhasil.")
                except Exception as e:
                    st.error(f"Gagal mengambil data iklim: {e}")
            st.rerun()
    with hb3:
        if seri_historis:
            st.caption(
                f"Harga: {len(seri_historis)} bulan ({seri_historis[0]['periode']} s/d {seri_historis[-1]['periode']}) · "
                f"ONI: {len(oni_historis)} bulan · Curah hujan: {len(hujan_historis.get('CIV-01', []))} bulan"
            )

    if not seri_historis:
        st.info("Belum ada data historis — tekan tombol di atas untuk mengambil dari ICCO.")
    else:
        tampil_oni = st.checkbox("Tampilkan overlay ONI (El Nino/La Nina)", value=bool(oni_historis))
        tampil_hujan = st.checkbox("Tampilkan overlay curah hujan Afrika Barat (anomali z-score)", value=bool(hujan_historis.get("CIV-01")))

        anomali_list = anomali.deteksi_anomali(seri_historis)

        df_hist = pd.DataFrame(seri_historis)
        df_hist["tanggal"] = pd.to_datetime(df_hist["periode"], format="%Y-%m")
        df_hist["warna_anomali"] = df_hist["periode"].apply(
            lambda p: next((a["arah"] for a in anomali_list if a["periode"] == p), None)
        )

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_hist["tanggal"], y=df_hist["index_usd_ton"],
            mode="lines", name="Index ICCO (US$/ton)",
            line=dict(color="#5FA331", width=2.5),
            fill="tozeroy", fillcolor="rgba(95,163,49,0.10)",
            hovertemplate="%{x|%b %Y}<br>US$ %{y:,.0f}/ton<extra></extra>",
            yaxis="y1",
        ))
        for arah, warna, simbol in [("naik", "#D64545", "triangle-up"), ("turun", "#1E88E5", "triangle-down")]:
            sub = df_hist[df_hist["warna_anomali"] == arah]
            if not sub.empty:
                fig.add_trace(go.Scatter(
                    x=sub["tanggal"], y=sub["index_usd_ton"],
                    mode="markers", name=f"Anomali {arah}",
                    marker=dict(color=warna, size=11, symbol=simbol, line=dict(color="white", width=1)),
                    hovertemplate="%{x|%b %Y}<br>US$ %{y:,.0f}/ton<br>Anomali " + arah + "<extra></extra>",
                    yaxis="y1",
                ))

        if tampil_oni and oni_historis:
            # Batasi ke rentang yang sama dengan data harga -- ONI NOAA punya
            # data sejak 1950, jauh lebih panjang dari harga ICCO (2005+);
            # tanpa dibatasi, rentang tanggal default grafik jadi 1950-2030
            # dan bagian harga yang justru jadi fokus utama malah terjepit kecil.
            _periode_awal_harga = seri_historis[0]["periode"]
            df_oni = pd.DataFrame([b for b in oni_historis if b["periode"] >= _periode_awal_harga])
            df_oni["tanggal"] = pd.to_datetime(df_oni["periode"], format="%Y-%m")
            fig.add_trace(go.Scatter(
                x=df_oni["tanggal"], y=df_oni["oni"],
                mode="lines", name="ONI (El Nino +/La Nina -)",
                line=dict(color="#E8A33D", width=1.6, dash="dot"),
                hovertemplate="%{x|%b %Y}<br>ONI %{y:+.2f}<extra></extra>",
                yaxis="y2",
            ))

        if tampil_hujan and hujan_historis.get("CIV-01"):
            hujan_seri = {b["periode"]: b["curah_hujan_mm"] for b in hujan_historis["CIV-01"]}
            hujan_z = korelasi.zscore_anomali_bulanan(hujan_seri)
            df_hujan = pd.DataFrame(sorted(hujan_z.items()), columns=["periode", "z"])
            df_hujan["tanggal"] = pd.to_datetime(df_hujan["periode"], format="%Y-%m")
            fig.add_trace(go.Scatter(
                x=df_hujan["tanggal"], y=df_hujan["z"],
                mode="lines", name="Curah hujan Pantai Gading (anomali z-score)",
                line=dict(color="#4FC3E8", width=1.4, dash="dash"),
                hovertemplate="%{x|%b %Y}<br>Anomali hujan %{y:+.2f}σ<extra></extra>",
                yaxis="y2",
            ))

        fig.update_layout(
            height=440,
            margin=dict(l=10, r=10, t=10, b=10),
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            xaxis=dict(
                rangeselector=dict(buttons=[
                    dict(count=1, label="1T", step="year", stepmode="backward"),
                    dict(count=3, label="3T", step="year", stepmode="backward"),
                    dict(count=5, label="5T", step="year", stepmode="backward"),
                    dict(step="all", label="Semua"),
                ]),
                rangeslider=dict(visible=True, thickness=0.06),
                type="date",
            ),
            yaxis=dict(title="US$/ton", gridcolor="rgba(255,255,255,0.08)"),
            yaxis2=dict(title="Indeks anomali iklim (~-3..+3)", overlaying="y", side="right", gridcolor="rgba(0,0,0,0)", zeroline=True, zerolinecolor="rgba(255,255,255,0.2)"),
        )
        st.plotly_chart(fig, width="stretch")

        if (tampil_oni and oni_historis) or (tampil_hujan and hujan_historis.get("CIV-01")):
            with st.expander("📐 Metodologi: analisis korelasi-lag iklim vs harga"):
                st.caption(
                    "Teknik standar riset dampak iklim-komoditas (cross-correlation): untuk tiap "
                    "jeda 0-6 bulan, dihitung korelasi Pearson antara indikator iklim bulan t dan "
                    "% perubahan harga bulan t+lag. Curah hujan dulu diubah jadi anomali z-score "
                    "per bulan kalender (menghilangkan pola musiman, mirip Standardized "
                    "Precipitation Index) supaya sebanding skalanya dengan ONI. **Ini korelasi, "
                    "bukan model prediksi** — dipakai untuk konteks, bukan sinyal beli/jual "
                    "otomatis (lihat prinsip P2, sistem ini tidak memprediksi harga)."
                )
                harga_usd = {b["periode"]: b["index_usd_ton"] for b in seri_historis}
                perubahan = korelasi.perubahan_pct_bulanan(harga_usd)
                if tampil_oni and oni_historis:
                    oni_seri = {b["periode"]: b["oni"] for b in oni_historis if b["periode"] in harga_usd}
                    top = korelasi.korelasi_lag(oni_seri, perubahan)
                    if top:
                        best = top[0]
                        st.markdown(
                            f"**ONI** — korelasi terkuat di lag **{best['lag_bulan']} bulan**: "
                            f"r = {best['r']:+.3f} ({korelasi.kekuatan_korelasi(best['r'])}, n={best['n']})"
                        )
                if tampil_hujan and hujan_historis.get("CIV-01"):
                    hujan_seri2 = {b["periode"]: b["curah_hujan_mm"] for b in hujan_historis["CIV-01"] if b["periode"] in harga_usd}
                    hujan_z2 = korelasi.zscore_anomali_bulanan(hujan_seri2)
                    top2 = korelasi.korelasi_lag(hujan_z2, perubahan)
                    if top2:
                        best2 = top2[0]
                        st.markdown(
                            f"**Curah hujan Pantai Gading** — korelasi terkuat di lag **{best2['lag_bulan']} bulan**: "
                            f"r = {best2['r']:+.3f} ({korelasi.kekuatan_korelasi(best2['r'])}, n={best2['n']})"
                        )
                st.caption(
                    "Korelasi yang lemah-sedang justru memvalidasi P2/P3: harga kakao digerakkan "
                    "banyak faktor sekaligus (spekulasi, rantai pasok, kurs), bukan satu indikator "
                    "iklim tunggal — karena itu Trading Guard fokus mengelola posisi & biaya, "
                    "bukan meramal arah harga dari satu sinyal."
                )

        if anomali_list:
            st.markdown("**🔍 Anomali terdeteksi (>2 standar deviasi dari volatilitas normal)**")
            for a in anomali_list[:8]:
                warna_bg = "🔴" if a["arah"] == "naik" else "🔵"
                with st.container(border=True):
                    st.markdown(f"{warna_bg} **{a['periode']}** — {a['pct_perubahan']:+.1f}% (z={a['z_score']})")
                    st.caption(a["analisa"])
                    st.markdown(f"**Rekomendasi:** {a['rekomendasi']}")
            if len(anomali_list) > 8:
                st.caption(f"...dan {len(anomali_list) - 8} anomali lain (tampil 8 terbaru).")
        else:
            st.caption("Tidak ada anomali >2 standar deviasi pada data yang tersimpan.")

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Harga pasar")
        if harga and harga.get("index_idr_per_kg"):
            m1, m2 = st.columns(2)
            m1.metric("Index (Rp/kg)", f"Rp {harga['index_idr_per_kg']:,.0f}".replace(",", "."))
            m2.metric("US$/ton", f"{harga.get('index_rekonstruksi_usd', 0):,.0f}".replace(",", "."))
            st.caption(f"Kurs Rp{harga.get('kurs_usd_idr', 0):,.0f}/USD · {harga.get('sumber', '—')}".replace(",", "."))
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
            fase_label = {"el_nino": "El Nino", "la_nina": "La Nina", "netral": "Netral"}.get(clim.get("fase"), "—")
            st.metric(f"ONI ({clim.get('periode', '—')})", f"{clim.get('oni', 0):+.2f}", fase_label)
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
            _kartu_cuaca(t["nama"], cuaca_per_titik.get(t["kode"]))

    st.divider()
    st.subheader("🌍 Cuaca Sabuk Produsen Global")
    st.caption(
        "Afrika Barat — pendorong utama index dunia, beda dari cuaca lokal di atas "
        "(itu soal risiko proses CGG sendiri). Dari catatan tim: \"kondisi iklim Utara\"."
    )
    if st.button("🔄 Ambil cuaca global terbaru"):
        with st.spinner("Mengambil data Open-Meteo untuk Pantai Gading & Ghana..."):
            try:
                scheduler.ingest_cuaca_global()
                st.success("Berhasil.")
            except Exception as e:
                st.error(f"Gagal mengambil cuaca global: {e}")
        st.rerun()
    cg1, cg2 = st.columns(2)
    for col, t in zip([cg1, cg2], cfg.get("titik_pantau_global", [])):
        with col:
            _kartu_cuaca(t["nama"], cuaca_global_per_titik.get(t["kode"]))

    st.divider()
    st.subheader("📨 Daily Brief")
    if st.button("Susun daily brief sekarang"):
        with st.spinner("Menyusun..."):
            teks = scheduler.kirim_daily_brief()
        st.session_state["brief_text"] = teks

    teks_brief = st.session_state.get("brief_text")
    if teks_brief:
        st.code(teks_brief, language=None)
        st.caption("Tersimpan sebagai file `.txt` di folder `data/` (di Streamlit Cloud, file ini hilang saat container restart — lihat catatan penyimpanan di README).")

        if email_sender.terkonfigurasi():
            if st.button("✉️ Kirim brief ini ke email"):
                with st.spinner("Mengirim..."):
                    ok, pesan = email_sender.kirim_email_brief(teks_brief)
                (st.success if ok else st.error)(pesan)
        else:
            st.caption(
                "Pengiriman email belum aktif — belum ada `[smtp]` di Streamlit Secrets. "
                "Tambahkan lewat **App settings → Secrets** (lihat contoh format di "
                "`src/notify/email_sender.py`). Pengiriman WhatsApp otomatis belum "
                "dihubungkan — butuh WhatsApp Business API dan izin eksplisit terpisah."
            )

# ---------------- TAB: Input Manual ----------------
if nav == "✍️ Input Manual":
    st.subheader("Harga hari ini")
    st.caption(
        "Sejak dashboard dibuka tadi, harga sudah dicoba diambil **otomatis** dari Yahoo "
        "Finance (kontrak depan ICE Cocoa NY) + kurs USD/IDR — lihat status di tab **💰 Buy "
        "Guard**. Form di bawah untuk **override manual** kalau fetch otomatis gagal, atau "
        "kalau Anda punya angka yang lebih Anda percaya (mis. dari broker langsung)."
    )
    if st.button("🔄 Coba ambil otomatis lagi sekarang", key="retry_auto_price"):
        with st.spinner("Mengambil dari Yahoo Finance + kurs..."):
            with db.get_connection() as conn:
                hasil = price.ambil_harga_hari_ini(conn)
        if hasil.get("status") == "KOSONG":
            st.error(hasil["pesan"])
        elif hasil.get("stale"):
            st.warning("Fetch otomatis gagal — masih pakai data lama. Isi manual di bawah kalau perlu.")
        else:
            st.success(f"Berhasil: Rp {hasil.get('index_idr_per_kg', 0):,.0f}/kg (sumber: {hasil.get('sumber')})".replace(",", "."))
        st.rerun()

    with st.expander("✍️ Isi / timpa manual"):
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

# ---------------- TAB: Parameter (7 Angka, spesifikasi bagian 11) ----------------
if nav == "⚙️ Parameter (7 Angka)":
    st.subheader("Isi tujuh angka yang wajib dikonfirmasi (Bagian 11 spesifikasi)")
    st.caption(
        "Ini yang membuat Buy Guard & Sell Guard berhenti memakai angka 0/template dan "
        "mulai memakai biaya asli CGG. Isi dari kontrak, invoice, atau catatan produksi — "
        "bukan estimasi kasar."
    )

    # Di luar form supaya label tombol simpan langsung bereaksi saat dicentang
    # (widget di dalam st.form baru "hidup" setelah tombol submit ditekan).
    nama_pengisi = st.text_input("Nama Anda (untuk jejak audit `diperbarui_oleh`)", key="nama_pengisi_param")
    konfirmasi = st.checkbox(
        "Saya konfirmasi seluruh angka di bawah ini berasal dari data aktual CGG "
        "(kontrak/invoice/catatan produksi) — bukan estimasi atau template.",
        key="konfirmasi_param",
    )
    if konfirmasi:
        st.success("Akan disimpan sebagai **TERVALIDASI** begitu ditekan.")
    else:
        st.caption("Belum dicentang → tetap tersimpan sebagai draft (status tetap BELUM DIVALIDASI).")

    with st.form("form_parameter"):
        st.markdown("**1 & 6 — Rendemen basah → kering** _(nilai tertimbang aktual; 6 = sebaran optimis/basis/konservatif)_")
        c1, c2, c3 = st.columns(3)
        rend_kons = c1.number_input("Konservatif (kg basah / kg kering)", min_value=1.0, step=0.01,
                                     value=float(cfg["rendemen"]["basah_ke_kering"]["konservatif"]))
        rend_basis = c2.number_input("Basis", min_value=1.0, step=0.01,
                                      value=float(cfg["rendemen"]["basah_ke_kering"]["basis"]))
        rend_opt = c3.number_input("Optimis", min_value=1.0, step=0.01,
                                    value=float(cfg["rendemen"]["basah_ke_kering"]["optimis"]))
        c4, c5 = st.columns(2)
        susut_kering = c4.number_input("Susut pengeringan (%)", min_value=0.0, step=0.1,
                                        value=float(cfg["rendemen"]["susut_pengeringan_pct"]))
        susut_sortasi = c5.number_input("Susut sortasi (%)", min_value=0.0, step=0.1,
                                         value=float(cfg["rendemen"]["susut_sortasi_pct"]))

        st.divider()
        st.markdown(
            "**Struktur biaya:** Harga Jual = _Biaya Pokok Produksi (Raw Material — "
            "dihitung Buy Guard, bukan input)_ + **Overhead Cost** + **Other Cost** + **Margin**."
        )

        st.markdown("**2 — Overhead Cost** _(Rp per kg kering — gabungan fermentasi, pengeringan, tenaga kerja, sortasi/packing, susut bobot)_")
        overhead_cost_input = st.number_input(
            "Overhead Cost", min_value=0.0, step=50.0,
            value=float(cfg["overhead_cost"]["nilai_rp_kg"]), key="overhead_cost_input",
        )

        st.divider()
        st.markdown("**3 — Other Cost** _(Rp per kg kering — freight ke buyer, penyimpanan gudang, alokasi biaya tetap)_")
        other_cost_input = st.number_input(
            "Other Cost", min_value=0.0, step=50.0,
            value=float(cfg["other_cost"]["nilai_rp_kg"]), key="other_cost_input",
        )

        st.markdown("_Freight tambahan per titik terima (kalau ada selisih ongkos angkut — ditambahkan di atas Other Cost):_")
        freight_titik = {}
        cols_titik = st.columns(len(cfg["titik_terima"]))
        for col, t in zip(cols_titik, cfg["titik_terima"]):
            freight_titik[t["kode"]] = col.number_input(
                f"{t['nama']} ({t['kode']})", min_value=0.0, step=50.0,
                value=float(t["freight_tambahan_rp_kg"]), key=f"freight_{t['kode']}",
            )

        st.divider()
        st.markdown("**4 — Premium aktual per segmen jual** _(dari kontrak/invoice, % terhadap harga index)_")
        p1, p2, p3 = st.columns(3)
        prem_artisan = p1.number_input("Artisan (%)", min_value=0.0, max_value=100.0, step=0.5,
                                        value=float(cfg["segmen_jual"]["artisan"]["premium_thd_index"]) * 100) / 100
        prem_pabrik = p2.number_input("Pabrik/chocolate maker (%)", min_value=0.0, max_value=100.0, step=0.5,
                                       value=float(cfg["segmen_jual"]["pabrik_chocolate_maker"]["premium_thd_index"]) * 100) / 100
        prem_trader = p3.number_input("Trader asalan (%)", min_value=0.0, max_value=100.0, step=0.5,
                                       value=float(cfg["segmen_jual"]["trader_asalan"]["premium_thd_index"]) * 100) / 100

        st.divider()
        st.markdown("**5 — Klarifikasi harga acuan**")
        catatan_klarifikasi = st.text_area(
            "\"Rp73.000/kg kering — ini harga beli atau harga jual?\" (tulis jawaban & konteksnya di sini untuk jejak audit)",
            value=cfg.get("catatan_klarifikasi_harga", ""),
            placeholder="mis. Rp73.000/kg adalah harga JUAL ke Trader X per kontrak Agustus 2026...",
        )

        st.divider()
        st.markdown("**6 — Komposisi penjualan 2025** _(persen volume ke tiap segmen — untuk konteks, belum dipakai di rumus)_")
        k1, k2, k3 = st.columns(3)
        existing_komposisi = cfg.get("komposisi_penjualan_2025", {"artisan": 0, "pabrik_chocolate_maker": 0, "trader_asalan": 0})
        komposisi_artisan = k1.number_input("% ke Artisan", min_value=0.0, max_value=100.0, step=1.0, value=float(existing_komposisi.get("artisan", 0)))
        komposisi_pabrik = k2.number_input("% ke Pabrik", min_value=0.0, max_value=100.0, step=1.0, value=float(existing_komposisi.get("pabrik_chocolate_maker", 0)))
        komposisi_trader = k3.number_input("% ke Trader", min_value=0.0, max_value=100.0, step=1.0, value=float(existing_komposisi.get("trader_asalan", 0)))
        if round(komposisi_artisan + komposisi_pabrik + komposisi_trader) not in (0, 100):
            st.caption("⚠️ Totalnya belum 100% — boleh disimpan dulu, lengkapi belakangan.")

        st.divider()
        st.markdown("**7 — Biaya modal & cost of carry**")
        m1, m2, m3, m4 = st.columns(4)
        biaya_modal_pct = m1.number_input("Biaya modal tahunan (%)", min_value=0.0, step=0.5,
                                           value=float(cfg["cost_of_carry"]["biaya_modal_tahunan_pct"]))
        gudang_carry = m2.number_input("Gudang (Rp/kg/bulan)", min_value=0.0, step=10.0,
                                        value=float(cfg["cost_of_carry"]["gudang_rp_per_kg_bulan"]))
        susut_carry = m3.number_input("Susut (%/bulan)", min_value=0.0, step=0.1,
                                       value=float(cfg["cost_of_carry"]["susut_pct_per_bulan"]))
        risiko_grade_carry = m4.number_input("Risiko turun grade (%/bulan)", min_value=0.0, step=0.1,
                                              value=float(cfg["cost_of_carry"]["risiko_turun_grade_pct_per_bulan"]))

        st.divider()
        st.markdown(
            "**Tambahan — Kalender Musim Panen Lokal** _(dari catatan tim; masih perkiraan, "
            "koreksi kalau salah — angka bulan 1=Jan ... 12=Des)_"
        )
        mp = cfg["musim_panen"]["lokal"]
        k1, k2, k3, k4 = st.columns(4)
        pu_mulai = k1.number_input("Panen utama — mulai bulan", min_value=1, max_value=12, step=1, value=int(mp["panen_utama"]["mulai_bulan"]))
        pu_selesai = k2.number_input("Panen utama — selesai bulan", min_value=1, max_value=12, step=1, value=int(mp["panen_utama"]["selesai_bulan"]))
        ps_mulai = k3.number_input("Panen sela — mulai bulan", min_value=1, max_value=12, step=1, value=int(mp["panen_sela"]["mulai_bulan"]))
        ps_selesai = k4.number_input("Panen sela — selesai bulan", min_value=1, max_value=12, step=1, value=int(mp["panen_sela"]["selesai_bulan"]))

        st.divider()
        simpan = st.form_submit_button("💾 Simpan & tandai TERVALIDASI" if konfirmasi else "💾 Simpan sebagai draft")

        if simpan:
            cfg["rendemen"]["basah_ke_kering"]["konservatif"] = rend_kons
            cfg["rendemen"]["basah_ke_kering"]["basis"] = rend_basis
            cfg["rendemen"]["basah_ke_kering"]["optimis"] = rend_opt
            cfg["rendemen"]["susut_pengeringan_pct"] = susut_kering
            cfg["rendemen"]["susut_sortasi_pct"] = susut_sortasi

            cfg["overhead_cost"]["nilai_rp_kg"] = overhead_cost_input
            cfg["other_cost"]["nilai_rp_kg"] = other_cost_input

            for t in cfg["titik_terima"]:
                t["freight_tambahan_rp_kg"] = freight_titik[t["kode"]]

            cfg["segmen_jual"]["artisan"]["premium_thd_index"] = prem_artisan
            cfg["segmen_jual"]["pabrik_chocolate_maker"]["premium_thd_index"] = prem_pabrik
            cfg["segmen_jual"]["trader_asalan"]["premium_thd_index"] = prem_trader

            cfg["catatan_klarifikasi_harga"] = catatan_klarifikasi
            cfg["komposisi_penjualan_2025"] = {
                "artisan": komposisi_artisan,
                "pabrik_chocolate_maker": komposisi_pabrik,
                "trader_asalan": komposisi_trader,
            }

            cfg["cost_of_carry"]["biaya_modal_tahunan_pct"] = biaya_modal_pct
            cfg["cost_of_carry"]["gudang_rp_per_kg_bulan"] = gudang_carry
            cfg["cost_of_carry"]["susut_pct_per_bulan"] = susut_carry
            cfg["cost_of_carry"]["risiko_turun_grade_pct_per_bulan"] = risiko_grade_carry

            cfg["musim_panen"]["lokal"]["panen_utama"]["mulai_bulan"] = int(pu_mulai)
            cfg["musim_panen"]["lokal"]["panen_utama"]["selesai_bulan"] = int(pu_selesai)
            cfg["musim_panen"]["lokal"]["panen_sela"]["mulai_bulan"] = int(ps_mulai)
            cfg["musim_panen"]["lokal"]["panen_sela"]["selesai_bulan"] = int(ps_selesai)

            if konfirmasi:
                cfg["meta"]["status"] = "TERVALIDASI"
            cfg["meta"]["diperbarui_oleh"] = nama_pengisi or cfg["meta"].get("diperbarui_oleh", "—")
            cfg["meta"]["terakhir_diperbarui"] = date.today().isoformat()

            yaml_baru = scheduler.save_config(cfg)
            st.session_state["yaml_baru"] = yaml_baru
            st.success(
                "Tersimpan"
                + (" dan status jadi TERVALIDASI." if konfirmasi else " sebagai draft (status tetap BELUM DIVALIDASI sampai dicentang & dikonfirmasi).")
            )
            st.rerun()

    yaml_baru = st.session_state.get("yaml_baru")
    if yaml_baru:
        st.divider()
        st.markdown(
            "**⚠️ Penting kalau app ini di Streamlit Cloud:** perubahan di atas hanya hidup "
            "selama container berjalan — hilang saat reboot/redeploy. Salin YAML final di bawah "
            "ini dan tempelkan ke `config/parameters.yaml` di repo GitHub Anda supaya permanen."
        )
        st.code(yaml_baru, language="yaml")

st.divider()
st.caption(
    f"Versi parameter: {cfg['meta']['versi']} · Status: {cfg['meta']['status']} · "
    f"Terakhir diperbarui: {cfg['meta']['terakhir_diperbarui']}"
)
