import hmac
import re

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import db
import optimizer as opt

st.set_page_config(page_title="Route Plan Optimizer", page_icon="🗺️", layout="wide")


# ---------- Password ----------
def check_password() -> bool:
    # Password hanya aktif kalau APP_PASSWORD diisi di Secrets
    if st.session_state.get("auth_ok") or not st.secrets.get("APP_PASSWORD"):
        return True
    st.title("🗺️ Route Plan Optimizer")
    pw = st.text_input("Masukkan password aplikasi", type="password")
    if pw and hmac.compare_digest(pw, st.secrets["APP_PASSWORD"]):
        st.session_state.auth_ok = True
        st.rerun()
    elif pw:
        st.error("Password salah.")
    return False


if not check_password():
    st.stop()


def parse_codes(text: str):
    tokens = [t.strip().strip("'\"").upper() for t in re.split(r"[\s,;]+", text or "") if t.strip()]
    seen, uniq, dup = set(), [], []
    for t in tokens:
        if t in seen:
            dup.append(t)
        else:
            seen.add(t)
            uniq.append(t)
    return uniq, dup


# ---------- Sidebar ----------
st.sidebar.header("⚙️ Pengaturan")
salesman = st.sidebar.text_input("Nama salesman (untuk nama file)")
quota = st.sidebar.number_input("Kunjungan per hari (Senin–Jumat)", 5, 150, 50, step=1)
st.sidebar.caption(f"Sabtu = **{quota // 2}** outlet · Kapasitas 2 minggu = **{opt.capacity(quota)}** outlet")
mode = st.sidebar.radio("Kalau jumlah kode tidak pas dengan kapasitas",
                        ["Proporsional", "Batasi kuota"],
                        help="Proporsional: semua kode masuk, dibagi rata.\n\n"
                             "Batasi kuota: tiap hari maksimal sesuai kuota, sisanya ditandai BELUM TERJADWAL.")
return_to_depot = st.sidebar.checkbox("Hitung perjalanan pulang ke titik awal", value=True)
with st.sidebar.expander("Pengaturan lanjutan"):
    factor = st.slider("Faktor jalan (× jarak garis lurus)", 1.0, 1.6, 1.3, 0.05)
    time_limit = st.slider("Waktu optimasi per hari (detik)", 1, 10, 2)
st.sidebar.markdown("---")
st.sidebar.caption("Develop Program By Nurman Catra")

# ---------- Input ----------
st.title("🗺️ Route Plan Optimizer")
text = st.text_area("Paste CUSTOMERNO di sini (boleh langsung copy satu kolom dari Excel)", height=180)

if st.button("🚀 Susun Jadwal", type="primary"):
    codes, dup = parse_codes(text)
    if not codes:
        st.warning("Belum ada kode yang di-paste.")
        st.stop()
    with st.spinner("Mengambil data outlet..."):
        outlets = db.fetch_outlets(tuple(codes))
    missing = sorted(set(codes) - set(outlets["CUSTOMERNO"]))
    if outlets.empty:
        st.error("Tidak ada kode yang ditemukan di database.")
        st.stop()
    bar = st.progress(0.0, text="Menyusun jadwal & rute...")
    plan = opt.build_plan(outlets, quota, mode, factor, return_to_depot, time_limit,
                          progress=lambda p: bar.progress(p, text=f"Menyusun rute... {int(p * 100)}%"))
    bar.empty()
    st.session_state.plan = plan
    st.session_state.meta = {"n_input": len(codes), "dup": dup, "missing": missing}

if "plan" not in st.session_state:
    st.stop()

plan, meta = st.session_state.plan, st.session_state.meta
cap = opt.capacity(quota)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Kode di-paste", meta["n_input"])
c2.metric("Ditemukan", len(plan))
c3.metric("Tidak ditemukan", len(meta["missing"]))
c4.metric("Kapasitas 2 minggu", cap)
if meta["dup"]:
    st.info(f"{len(meta['dup'])} kode dobel diabaikan: {', '.join(meta['dup'][:20])}")
if meta["missing"]:
    st.warning("Kode tidak ada di database (atau koordinatnya kosong): " + ", ".join(meta["missing"][:50]))
if len(plan) > cap:
    st.warning(f"Jumlah outlet ({len(plan)}) melebihi kapasitas ({cap}). "
               f"Supaya semua masuk, kuota minimal **{-(-len(plan) // 11)}/hari**.")

tab_map, tab_edit, tab_sum, tab_exp = st.tabs(["🗺️ Peta", "✏️ Revisi", "📊 Ringkasan", "📥 Download Excel"])

PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#00a5a5",
           "#f032e6", "#7a9c00", "#008080", "#9a6324", "#800000", "#000075"]

with tab_map:
    slots = list(opt.build_slots(quota)["SLOT"])
    pilih = st.selectbox("Tampilkan hari", ["Semua"] + slots)
    m = folium.Map(location=opt.DEPOT, zoom_start=12, tiles="cartodbpositron")
    folium.Marker(opt.DEPOT, tooltip="TITIK AWAL", icon=folium.Icon(color="red", icon="home")).add_to(m)
    for i, s in enumerate(slots):
        if pilih not in ("Semua", s):
            continue
        g = plan[plan["SLOT"] == s].sort_values("URUTAN")
        if g.empty:
            continue
        pts = [list(opt.DEPOT)] + g[["LATITUDE", "LONGITUDE"]].values.tolist()
        if return_to_depot:
            pts.append(list(opt.DEPOT))
        folium.PolyLine(pts, color=PALETTE[i], weight=2, opacity=0.8).add_to(m)
        for r in g.itertuples():
            folium.CircleMarker([r.LATITUDE, r.LONGITUDE], radius=5, color=PALETTE[i], fill=True,
                                fill_opacity=0.9,
                                tooltip=f"{s} #{int(r.URUTAN)} — {r.CUSTOMERNO} {r.NAMA_OUTLET or ''}").add_to(m)
    for r in plan[plan["WEEK"] == opt.UNSCHEDULED].itertuples():
        folium.CircleMarker([r.LATITUDE, r.LONGITUDE], radius=6, color="black",
                            tooltip=f"BELUM TERJADWAL {r.CUSTOMERNO}").add_to(m)
    st_folium(m, height=600, use_container_width=True, returned_objects=[])

with tab_edit:
    st.markdown("**Cara revisi:** ubah kolom **Week / Hari** untuk memindah outlet, "
                "atau ubah **Urutan** (boleh 3.5 untuk menyisip di antara 3 dan 4). "
                "Lalu klik salah satu tombol di bawah tabel.")
    with st.form("revisi"):
        edited = st.data_editor(
            plan[["WEEK", "HARI", "URUTAN", "CUSTOMERNO", "NAMA_OUTLET", "ALAMAT", "JARAK_KM", "KUMULATIF_KM"]],
            column_config={
                "WEEK": st.column_config.SelectboxColumn("Week", options=opt.WEEKS + [opt.UNSCHEDULED], required=True),
                "HARI": st.column_config.SelectboxColumn("Hari", options=opt.HARI + [opt.UNSCHEDULED], required=True),
                "URUTAN": st.column_config.NumberColumn("Urutan", min_value=0, step=0.5),
            },
            disabled=["CUSTOMERNO", "NAMA_OUTLET", "ALAMAT", "JARAK_KM", "KUMULATIF_KM"],
            hide_index=True, height=500, use_container_width=True)
        b1, b2 = st.columns(2)
        hitung = b1.form_submit_button("🔁 Simpan revisi (pakai urutan saya)")
        optim = b2.form_submit_button("⚡ Simpan revisi + rapikan rute otomatis")
    if hitung or optim:
        old = plan.set_index("CUSTOMERNO")
        new = plan.copy()
        ed = edited.set_index("CUSTOMERNO")
        new["WEEK"] = new["CUSTOMERNO"].map(ed["WEEK"])
        new["HARI"] = new["CUSTOMERNO"].map(ed["HARI"])
        new["URUTAN"] = new["CUSTOMERNO"].map(ed["URUTAN"]).astype(float)
        # satukan isian: kalau salah satu BELUM TERJADWAL, dua-duanya BELUM TERJADWAL
        un = (new["WEEK"] == opt.UNSCHEDULED) | (new["HARI"] == opt.UNSCHEDULED)
        new.loc[un, ["WEEK", "HARI"]] = opt.UNSCHEDULED
        prev_w = new["CUSTOMERNO"].map(old["WEEK"])
        prev_h = new["CUSTOMERNO"].map(old["HARI"])
        prev_u = new["CUSTOMERNO"].map(old["URUTAN"])
        moved = (new["WEEK"] != prev_w) | (new["HARI"] != prev_h)
        # outlet pindah hari tanpa diberi urutan baru -> taruh paling akhir
        new.loc[moved & (new["URUTAN"] == prev_u), "URUTAN"] = 9999
        if optim:
            changed = set(zip(new.loc[moved, "WEEK"], new.loc[moved, "HARI"])) | \
                      set(zip(prev_w[moved], prev_h[moved]))
            for w, h in changed:
                if w == opt.UNSCHEDULED:
                    continue
                sub = new[(new["WEEK"] == w) & (new["HARI"] == h)]
                if len(sub):
                    new.loc[sub.index, "URUTAN"] = opt.optimize_slot(sub, factor, return_to_depot, time_limit)
        st.session_state.plan = opt.compute_distances(new, factor)
        st.rerun()

ring = opt.summary(plan, quota, factor, return_to_depot)

with tab_sum:
    st.dataframe(ring, hide_index=True, use_container_width=True)
    over = ring[ring["SELISIH"] > 0]
    if len(over):
        st.warning("Hari yang melebihi kuota: " +
                   ", ".join(f"{r.WEEK}-{r.HARI} (+{r.SELISIH})" for r in over.itertuples()))
    st.metric("Total jarak 2 minggu (perkiraan)", f"{ring['TOTAL_KM'].sum():,.1f} km")

with tab_exp:
    info = {"Salesman": salesman, "Kuota/hari": quota, "Kuota Sabtu": quota // 2, "Mode": mode,
            "Faktor jalan": factor, "Pulang ke titik awal": return_to_depot,
            "Titik awal": f"{opt.DEPOT[0]}, {opt.DEPOT[1]}"}
    st.download_button("📥 Download Excel", data=opt.to_excel_bytes(plan, ring, info),
                       file_name=f"RoutePlan_{salesman or 'salesman'}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       type="primary")
