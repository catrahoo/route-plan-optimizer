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
    for c in ["LATITUDE", "LONGITUDE"]:
        outlets[c] = pd.to_numeric(outlets[c], errors="coerce")
    ok_mask = opt.valid_coord(outlets["LATITUDE"], outlets["LONGITUDE"]).to_numpy()
    good, nocoord = outlets[ok_mask], outlets[~ok_mask]
    if good.empty:
        plan = opt.empty_plan(outlets.columns)
    else:
        bar = st.progress(0.0, text="Menyusun jadwal & rute...")
        plan = opt.build_plan(good, quota, mode, factor, return_to_depot, time_limit,
                              progress=lambda p: bar.progress(p, text=f"Menyusun rute... {int(p * 100)}%"))
        bar.empty()
    st.session_state.plan = plan
    st.session_state.meta = {"n_input": len(codes), "dup": dup, "missing": missing}
    nc = nocoord.copy()
    nc.insert(3, "KOORDINAT_GMAPS", "")
    st.session_state.nc_base = nc.reset_index(drop=True)
    st.session_state.nc_ver = st.session_state.get("nc_ver", 0) + 1
    st.session_state.pop("last_click", None)

if "plan" not in st.session_state:
    st.stop()

plan, meta = st.session_state.plan, st.session_state.meta
nc_base = st.session_state.get("nc_base", pd.DataFrame(columns=["CUSTOMERNO", "NAMA_OUTLET", "ALAMAT", "KOORDINAT_GMAPS", "LATITUDE", "LONGITUDE"]))
st.session_state.setdefault("nc_ver", 0)
cap = opt.capacity(quota)
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Kode di-paste", meta["n_input"])
c2.metric("Masuk jadwal", int((plan["WEEK"] != opt.UNSCHEDULED).sum()))
c3.metric("Tanpa koordinat", len(nc_base))
c4.metric("Tidak ada di database", len(meta["missing"]))
c5.metric("Kapasitas 2 minggu", cap)
if meta["dup"]:
    st.info(f"{len(meta['dup'])} kode dobel diabaikan: {', '.join(meta['dup'][:20])}")
n_masalah = len(nc_base) + len(meta["missing"])
if n_masalah:
    st.warning(f"Ada {n_masalah} outlet yang belum bisa dijadwalkan. Buka tab **⚠️ Data Belum Lengkap** untuk melengkapinya.")
if len(plan) > cap:
    st.warning(f"Jumlah outlet ({len(plan)}) melebihi kapasitas ({cap}). "
               f"Supaya semua masuk, kuota minimal **{-(-len(plan) // 11)}/hari**.")
if st.session_state.pop("fix_msg", None):
    st.success("✅ Koordinat tersimpan ke database dan outlet sudah dimasukkan ke jadwal (hari terdekat).")

tab_map, tab_edit, tab_sum, tab_fix, tab_exp = st.tabs(
    ["🗺️ Peta", "✏️ Revisi", "📊 Ringkasan", f"⚠️ Data Belum Lengkap ({n_masalah})", "📥 Download Excel"])

PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#00a5a5",
           "#f032e6", "#7a9c00", "#008080", "#9a6324", "#800000", "#000075"]

with tab_map:
    slots = list(opt.build_slots(quota)["SLOT"])
    pilih = st.selectbox("Tampilkan hari", ["Semua"] + slots)
    m = folium.Map(location=opt.DEPOT, zoom_start=12, tiles="OpenStreetMap")
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

with tab_fix:
    st.subheader(f"📍 Outlet tanpa koordinat / koordinat di luar area ({len(nc_base)})")
    if nc_base.empty:
        st.success("Semua outlet sudah punya koordinat.")
    else:
        st.markdown(
            "Isi koordinat dengan salah satu cara:\n"
            "1. **Paste dari Google Maps** ke kolom *Koordinat GMaps* (contoh: `-7.2592, 112.6936`), atau\n"
            "2. Ketik langsung di kolom **Latitude** dan **Longitude**, atau\n"
            "3. **Pilih outlet** di bawah tabel, lalu **klik lokasinya di peta**.\n\n"
            "Setelah itu klik **💾 Simpan koordinat**. Koordinat tersimpan ke database "
            "dan outlet otomatis masuk ke jadwal.")
        edited_nc = st.data_editor(
            nc_base[["CUSTOMERNO", "NAMA_OUTLET", "ALAMAT", "KOORDINAT_GMAPS", "LATITUDE", "LONGITUDE"]],
            column_config={
                "KOORDINAT_GMAPS": st.column_config.TextColumn("Koordinat GMaps (paste di sini)"),
                "LATITUDE": st.column_config.NumberColumn("Latitude", format="%.7f"),
                "LONGITUDE": st.column_config.NumberColumn("Longitude", format="%.7f"),
            },
            disabled=["CUSTOMERNO", "NAMA_OUTLET", "ALAMAT"],
            hide_index=True, use_container_width=True, key=f"nc_{st.session_state.nc_ver}")
        cur = nc_base.copy()
        for c in ["KOORDINAT_GMAPS", "LATITUDE", "LONGITUDE"]:
            cur[c] = edited_nc[c].values
        for i, r in cur.iterrows():
            if str(r.KOORDINAT_GMAPS or "").strip():
                la, lo = opt.parse_gmaps(r.KOORDINAT_GMAPS)
                if la is not None:
                    cur.at[i, "LATITUDE"], cur.at[i, "LONGITUDE"] = la, lo
        cur["LATITUDE"] = pd.to_numeric(cur["LATITUDE"], errors="coerce")
        cur["LONGITUDE"] = pd.to_numeric(cur["LONGITUDE"], errors="coerce")
        cur["_OK"] = opt.valid_coord(cur["LATITUDE"], cur["LONGITUDE"]).to_numpy()

        label = (cur["CUSTOMERNO"] + " — " + cur["NAMA_OUTLET"].fillna("")
                 + cur["_OK"].map({True: "  ✅", False: ""})).tolist()
        idx = st.selectbox("Pilih outlet yang mau ditandai di peta", range(len(cur)),
                           format_func=lambda i: label[i])
        sel = cur.iloc[idx]
        center = [sel.LATITUDE, sel.LONGITUDE] if sel["_OK"] else list(opt.DEPOT)
        m2 = folium.Map(location=center, zoom_start=16 if sel["_OK"] else 12, tiles="OpenStreetMap")
        folium.Marker(opt.DEPOT, tooltip="TITIK AWAL", icon=folium.Icon(color="red", icon="home")).add_to(m2)
        for r in plan[plan["WEEK"] != opt.UNSCHEDULED].itertuples():
            folium.CircleMarker([r.LATITUDE, r.LONGITUDE], radius=3, color="#999999", fill=True,
                                tooltip=f"{r.CUSTOMERNO} {r.NAMA_OUTLET or ''}").add_to(m2)
        for i, r in cur[cur["_OK"]].iterrows():
            if i != idx:
                folium.CircleMarker([r.LATITUDE, r.LONGITUDE], radius=6, color="#4363d8", fill=True,
                                    tooltip=f"{r.CUSTOMERNO} {r.NAMA_OUTLET or ''}").add_to(m2)
        if sel["_OK"]:
            folium.Marker([sel.LATITUDE, sel.LONGITUDE], tooltip=f"{sel.CUSTOMERNO} {sel.NAMA_OUTLET or ''}",
                          icon=folium.Icon(color="green", icon="star")).add_to(m2)
        st.caption(f"👆 Klik di peta untuk menaruh lokasi **{sel.CUSTOMERNO} — {sel.NAMA_OUTLET or ''}**. "
                   "Titik abu-abu = outlet yang sudah terjadwal.")
        out = st_folium(m2, height=500, use_container_width=True,
                        returned_objects=["last_clicked"], key="map_fix")
        click = (out or {}).get("last_clicked")
        if click and click != st.session_state.get("last_click"):
            st.session_state.last_click = click
            base = cur.drop(columns="_OK")
            base.at[idx, "LATITUDE"] = round(click["lat"], 7)
            base.at[idx, "LONGITUDE"] = round(click["lng"], 7)
            base.at[idx, "KOORDINAT_GMAPS"] = ""
            st.session_state.nc_base = base
            st.session_state.nc_ver += 1
            st.rerun()

        siap = cur[cur["_OK"]]
        salah = cur[cur["LATITUDE"].notna() & ~cur["_OK"]]
        if len(salah):
            st.warning("Koordinat ini di luar Surabaya Raya, cek lagi: " + ", ".join(salah["CUSTOMERNO"]))
        if st.button(f"💾 Simpan koordinat ({len(siap)} outlet)", type="primary", disabled=siap.empty):
            with st.spinner("Menyimpan ke database..."):
                for r in siap.itertuples():
                    db.update_coords(r.CUSTOMERNO, r.LATITUDE, r.LONGITUDE)
                new = siap.drop(columns=["_OK", "KOORDINAT_GMAPS"])
                st.session_state.plan = opt.add_outlets(plan, new, quota, factor, return_to_depot, time_limit)
                st.session_state.nc_base = cur[~cur["_OK"]].drop(columns="_OK").reset_index(drop=True)
                st.session_state.nc_ver += 1
                st.session_state.fix_msg = True
            st.rerun()

    st.subheader(f"❓ Kode tidak ada di database ({len(meta['missing'])})")
    if meta["missing"]:
        st.caption("Kode ini tidak ada di master outlet. Cek apakah salah ketik, atau outlet baru yang belum ada di master.")
        st.dataframe(pd.DataFrame({"CUSTOMERNO": meta["missing"]}), hide_index=True)
    else:
        st.success("Semua kode ada di database.")

with tab_exp:
    info = {"Salesman": salesman, "Kuota/hari": quota, "Kuota Sabtu": quota // 2, "Mode": mode,
            "Faktor jalan": factor, "Pulang ke titik awal": return_to_depot,
            "Titik awal": f"{opt.DEPOT[0]}, {opt.DEPOT[1]}"}
    st.download_button("📥 Download Excel", data=opt.to_excel_bytes(plan, ring, info),
                       file_name=f"RoutePlan_{salesman or 'salesman'}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       type="primary")
