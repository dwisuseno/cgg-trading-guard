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
from src.notify import email_sender

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


# ---------------- Auto-bootstrap: sekali per sesi, isi data hari ini kalau kosong ----------------
# Streamlit Cloud tidak menjalankan scheduler.py di latar belakang (lihat README) --
# jadi dashboard sendiri yang menutup celah itu: begitu ada orang membuka halaman
# ini, ia mengecek data hari ini dan menariknya kalau belum ada, meniru job `pagi()`
# tanpa perlu proses cron terpisah. Harga tetap TIDAK di-auto-isi (Layer 3 sengaja
# manual, lihat spesifikasi bagian 3.1) -- hanya iklim, cuaca, dan Buy Guard turunannya.
if not st.session_state.get("bootstrapped_today") == date.today().isoformat():
    with st.spinner("Menyiapkan data hari ini (iklim, cuaca)..."):
        with db.get_connection() as _conn:
            _clim = db.latest_climate(_conn)
            _need_climate = not _clim or _clim.get("periode", "")[:4] != str(date.today().year)
            _need_weather = any(
                (db.latest_weather(_conn, t["kode"]) or {}).get("tanggal") != date.today().isoformat()
                for t in cfg["titik_terima"]
            )
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
        # Buy Guard ikut dihitung ulang otomatis kalau harga hari ini sudah ada
        with db.get_connection() as _conn:
            _harga = db.latest_market_price(_conn)
        if _harga and _harga.get("index_idr_per_kg") and _harga.get("tanggal") == date.today().isoformat():
            try:
                scheduler.hitung_buy_guard()
            except Exception as e:
                st.toast(f"Gagal auto-hitung Buy Guard: {e}", icon="⚠️")
    st.session_state["bootstrapped_today"] = date.today().isoformat()

tab_beli, tab_jual, tab_data, tab_input, tab_param = st.tabs(
    ["💰 Buy Guard", "📦 Sell Guard", "📊 Data Pasar & Iklim", "✍️ Input Manual", "⚙️ Parameter (7 Angka)"]
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
                st.dataframe(basah[cols].style.format("{:,.0f}"), width="stretch")
            with c2:
                st.markdown("**Kering (Rp/kg)**")
                st.dataframe(kering[cols].style.format("{:,.0f}"), width="stretch")
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

# ---------------- TAB: Parameter (7 Angka, spesifikasi bagian 11) ----------------
with tab_param:
    st.subheader("Isi tujuh angka yang wajib dikonfirmasi (Bagian 11 spesifikasi)")
    st.caption(
        "Ini yang membuat Buy Guard & Sell Guard berhenti memakai angka 0/template dan "
        "mulai memakai biaya asli CGG. Isi dari kontrak, invoice, atau catatan produksi — "
        "bukan estimasi kasar."
    )

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
        st.markdown("**2 — Biaya proses** _(Rp per kg KERING)_")
        b1, b2, b3, b4, b5 = st.columns(5)
        biaya_fermentasi = b1.number_input("Fermentasi", min_value=0.0, step=50.0, value=float(cfg["biaya_proses"]["fermentasi"]))
        biaya_pengeringan = b2.number_input("Pengeringan", min_value=0.0, step=50.0, value=float(cfg["biaya_proses"]["pengeringan"]))
        biaya_tenaga = b3.number_input("Tenaga kerja", min_value=0.0, step=50.0, value=float(cfg["biaya_proses"]["tenaga_kerja"]))
        biaya_sortasi = b4.number_input("Sortasi & packing", min_value=0.0, step=50.0, value=float(cfg["biaya_proses"]["sortasi_packing"]))
        biaya_susut = b5.number_input("Susut bobot", min_value=0.0, step=50.0, value=float(cfg["biaya_proses"]["susut_bobot"]))

        st.divider()
        st.markdown("**3 — Overhead** _(Rp per kg kering, kecuali disebutkan lain)_")
        o1, o2, o3, o4 = st.columns(4)
        ovh_freight = o1.number_input("Freight ke buyer", min_value=0.0, step=50.0, value=float(cfg["overhead"]["freight_ke_buyer"]))
        ovh_gudang = o2.number_input("Penyimpanan gudang", min_value=0.0, step=50.0, value=float(cfg["overhead"]["penyimpanan_gudang"]))
        ovh_umum = o3.number_input("Overhead umum (alokasi)", min_value=0.0, step=50.0, value=float(cfg["overhead"]["overhead_umum"]))
        ovh_susut_bln = o4.number_input("Susut simpan (%/bulan)", min_value=0.0, step=0.1, value=float(cfg["overhead"]["susut_penyimpanan_pct_per_bulan"]))

        st.markdown("_Freight tambahan per titik terima (kalau ada selisih ongkos angkut):_")
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
        nama_pengisi = st.text_input("Nama Anda (untuk jejak audit `diperbarui_oleh`)")
        konfirmasi = st.checkbox(
            "Saya konfirmasi seluruh angka di atas berasal dari data aktual CGG "
            "(kontrak/invoice/catatan produksi) — bukan estimasi atau template."
        )
        simpan = st.form_submit_button("💾 Simpan & tandai TERVALIDASI" if konfirmasi else "💾 Simpan sebagai draft")

        if simpan:
            cfg["rendemen"]["basah_ke_kering"]["konservatif"] = rend_kons
            cfg["rendemen"]["basah_ke_kering"]["basis"] = rend_basis
            cfg["rendemen"]["basah_ke_kering"]["optimis"] = rend_opt
            cfg["rendemen"]["susut_pengeringan_pct"] = susut_kering
            cfg["rendemen"]["susut_sortasi_pct"] = susut_sortasi

            cfg["biaya_proses"]["fermentasi"] = biaya_fermentasi
            cfg["biaya_proses"]["pengeringan"] = biaya_pengeringan
            cfg["biaya_proses"]["tenaga_kerja"] = biaya_tenaga
            cfg["biaya_proses"]["sortasi_packing"] = biaya_sortasi
            cfg["biaya_proses"]["susut_bobot"] = biaya_susut

            cfg["overhead"]["freight_ke_buyer"] = ovh_freight
            cfg["overhead"]["penyimpanan_gudang"] = ovh_gudang
            cfg["overhead"]["overhead_umum"] = ovh_umum
            cfg["overhead"]["susut_penyimpanan_pct_per_bulan"] = ovh_susut_bln

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
