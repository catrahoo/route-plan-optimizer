import hmac
import re

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import db
import optimizer as opt
import plan_b as pb
from roads import ORS, RoadError

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


def get_ors():
    """Objek OpenRouteService (disimpan di sesi supaya hasil jalan tidak diminta ulang)."""
    sec = st.secrets.get("ors", {})
    key = sec.get("key") if hasattr(sec, "get") else None
    key = key or st.secrets.get("ORS_KEY")
    if not key:
        return None
    if st.session_state.get("ors_key") != key:
        st.session_state.ors_obj = ORS(key)
        st.session_state.ors_key = key
    return st.session_state.ors_obj


ors = get_ors()


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
quota = st.sidebar.number_input("Kunjungan per hari (Senin–Jumat)", 5, 150, 40, step=1)
st.sidebar.caption("Sabtu Half Day (50% Cover)")
mode = st.sidebar.radio("Hari kerja",
                        ["Proporsional", "Custom Day"],
                        help="Proporsional: Senin–Sabtu kerja semua, outlet dibagi rata.\n\n"
                             "Custom Day: pilih sendiri hari kerjanya. Hari yang tidak dicentang = libur, "
                             "outletnya dibagi ke hari kerja lain (kunjungan per hari jadi lebih banyak).")
off_days = set()
if mode == "Custom Day":
    st.sidebar.caption("Centang hari kerja. Yang **tidak dicentang = hari libur**.")
    for w in opt.WEEKS:
        st.sidebar.markdown(f"**Week {w}**")
        cols = st.sidebar.columns(3)
        for i, h in enumerate(opt.HARI):
            if not cols[i % 3].checkbox(h, value=True, key=f"kerja_{w}_{h}"):
                off_days.add((w, h))
    if len(off_days) == len(opt.WEEKS) * len(opt.HARI):
        st.sidebar.error("Minimal harus ada 1 hari kerja.")
        st.stop()
q_cfg = (quota, frozenset(off_days))      # kuota + hari libur, dipakai semua perhitungan
return_to_depot = st.sidebar.checkbox("Hitung perjalanan pulang ke titik awal", value=True)
with st.sidebar.expander("Pengaturan lanjutan"):
    factor = st.slider("Faktor jalan (× jarak garis lurus)", 1.0, 1.6, 1.3, 0.05)
    time_limit = st.slider("Waktu optimasi per hari (detik)", 1, 10, 2)
st.sidebar.markdown("---")
st.sidebar.subheader("🛣️ Plan B (by jalan)")
if ors:
    use_b = st.sidebar.checkbox("Buat juga Plan B", value=True,
                                help="Memakai jarak jalan sungguhan (OpenRouteService). Butuh ±2–3 menit.")
else:
    use_b = False
    st.sidebar.info("Plan B belum aktif. Tambahkan API key OpenRouteService di Secrets "
                    "(bagian `[ors]`, isi `key = \"...\"`).")
st.sidebar.markdown("---")
st.sidebar.caption("Develop Program By Nurman Catra")

# ---------- Input ----------
st.title("🗺️ Route Plan Optimizer")
text = st.text_area("Silahkan Copas CODE CUSTOMER disini Ya....", height=180)

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
    # Plan A: outlet tanpa koordinat ikut dijadwalkan dengan lokasi perkiraan
    #   1) nama jalan sama di Sales District yang sama, 2) titik tengah Sales District
    est = pd.DataFrame(columns=list(outlets.columns) + ["KETERANGAN"])
    if len(nocoord):
        dists = tuple(sorted(set(nocoord["SALES_DISTRICT"].dropna())))
        with st.spinner("Memperkirakan lokasi outlet tanpa koordinat..."):
            ref = pd.concat([good[["CUSTOMERNO", "NAMA_OUTLET", "ALAMAT", "SALES_DISTRICT", "LATITUDE", "LONGITUDE"]],
                             db.fetch_district_refs(dists)], ignore_index=True).drop_duplicates("CUSTOMERNO")
            est = opt.estimate_coords(nocoord, ref)
    good_a = pd.concat([good.assign(KETERANGAN=""), est], ignore_index=True)
    if good_a.empty:
        plan = opt.empty_plan(list(outlets.columns) + ["KETERANGAN"])
    else:
        bar = st.progress(0.0, text="Menyusun jadwal & rute...")
        plan = opt.build_plan(good_a, q_cfg, mode, factor, return_to_depot, time_limit,
                              progress=lambda p: bar.progress(p, text=f"Menyusun rute... {int(p * 100)}%"))
        bar.empty()
    st.session_state.plans = {"A": plan, "B": None}
    st.session_state.road = {"A": None, "B": None}
    st.session_state.active = "A"
    if use_b and not good.empty:
        with st.status("Menyusun Plan B (by jalan)... ±2–3 menit", expanded=True) as stt:
            bar_b = st.progress(0.0)
            try:
                bar_b.progress(0.02, text="Menghitung jarak jalan Plan A untuk pembanding...")
                _, gA, rA = pb.apply_road(plan, ors, return_to_depot)
                st.session_state.road["A"] = (gA, rA)
                plan_tanpa_perkiraan = plan[plan["KETERANGAN"].fillna("") == ""]
                dfB, gB, rB = pb.build_plan_b(plan_tanpa_perkiraan, ors, q_cfg, factor, return_to_depot, time_limit,
                                              step=lambda m, p: bar_b.progress(min(1.0, p), text=m))
                st.session_state.plans["B"] = dfB
                st.session_state.road["B"] = (gB, rB)
                st.session_state.active = "B"
                stt.update(label="Plan B selesai ✅", state="complete", expanded=False)
            except RoadError as e:
                stt.update(label="Plan B gagal", state="error")
                st.error(f"❌ {e}  \nPlan A tetap bisa dipakai.")
    st.session_state.meta = {"n_input": len(codes), "dup": dup, "missing": missing}
    nc = nocoord.copy()
    nc.insert(3, "KOORDINAT_GMAPS", "")
    st.session_state.nc_base = nc.reset_index(drop=True)
    st.session_state.nc_ver = st.session_state.get("nc_ver", 0) + 1
    st.session_state.pop("last_click", None)

if "plans" not in st.session_state:
    st.stop()

plans, road, meta = st.session_state.plans, st.session_state.road, st.session_state.meta
if plans["B"] is not None:
    pilihan = st.radio("Plan yang dipakai untuk **Revisi** & **Download**", ["Plan A (by gruping)", "Plan B (by jalan)"],
                       index=1 if st.session_state.active == "B" else 0, horizontal=True)
    st.session_state.active = "B" if pilihan.startswith("Plan B") else "A"
active = st.session_state.active
plan = plans[active]


def save_plan(df, key=None):
    """Simpan plan (A/B) lalu perbarui jarak jalan kalau tersedia."""
    key = key or active
    if ors and (key == "B" or road.get(key) is not None):
        try:
            df_road, g, r = pb.apply_road(df, ors, return_to_depot)
            road[key] = (g, r)
            if key == "B":          # Plan B memakai jarak jalan; Plan A tetap garis lurus
                df = df_road
        except RoadError as e:
            st.warning(f"Jarak jalan tidak bisa diperbarui: {e}")
    plans[key] = df
nc_base = st.session_state.get("nc_base", pd.DataFrame(columns=["CUSTOMERNO", "NAMA_OUTLET", "ALAMAT", "KOORDINAT_GMAPS", "LATITUDE", "LONGITUDE"]))
st.session_state.setdefault("nc_ver", 0)
cap = opt.capacity(q_cfg)
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Kode di-paste", meta["n_input"])
c2.metric("Masuk jadwal", int((plan["WEEK"] != opt.UNSCHEDULED).sum()))
c3.metric("Tanpa koordinat", len(nc_base))
c4.metric("Tidak ada di database", len(meta["missing"]))
c5.metric("Kapasitas 2 minggu", cap)
if meta["dup"]:
    st.info(f"{len(meta['dup'])} kode dobel diabaikan: {', '.join(meta['dup'][:20])}")
n_masalah = len(nc_base) + len(meta["missing"])
n_est = int(plans["A"]["KETERANGAN"].fillna("").str.startswith(opt.NO_LONGLAT).sum()) if "KETERANGAN" in plans["A"] else 0
if n_masalah:
    st.warning(f"Ada {n_masalah} outlet tanpa koordinat / tidak ada di database. "
               + (f"{n_est} di antaranya ditaruh di **Plan A** dengan lokasi perkiraan ({opt.NO_LONGLAT}). " if n_est else "")
               + "Lengkapi koordinatnya di tab **⚠️ Data Belum Lengkap**.")
if len(plan) > cap:
    st.warning(f"Jumlah outlet ({len(plan)}) melebihi kapasitas ({cap}). "
               f"Supaya semua masuk, kuota minimal **{-(-len(plan) * quota // max(cap, 1))}/hari**.")
if st.session_state.pop("fix_msg", None):
    st.success("✅ Koordinat tersimpan ke database dan outlet sudah dimasukkan ke jadwal (hari terdekat).")

tab_a, tab_b, tab_edit, tab_sum, tab_fix, tab_exp = st.tabs(
    ["🗺️ Peta A (by gruping)", "🛣️ Peta B (by jalan)", f"✏️ Revisi (Plan {active})", "📊 Ringkasan",
     f"⚠️ Data Belum Lengkap ({n_masalah})", "📥 Download Excel"])

PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#00a5a5",
           "#f032e6", "#7a9c00", "#008080", "#9a6324", "#800000", "#000075"]

def draw_map(df, geoms, key, pilih):
    slots = list(opt.build_slots(q_cfg).query("not LIBUR")["SLOT"])
    m = folium.Map(location=opt.DEPOT, zoom_start=12, tiles="OpenStreetMap")
    folium.Marker(opt.DEPOT, tooltip="TITIK AWAL", icon=folium.Icon(color="red", icon="home")).add_to(m)
    for i, s in enumerate(slots):
        if pilih not in ("Semua", s):
            continue
        g = df[df["SLOT"] == s].sort_values("URUTAN")
        if g.empty:
            continue
        k = tuple(s.split(" - "))
        if geoms and k in geoms:
            line = geoms[k][0]
        else:
            line = [list(opt.DEPOT)] + g[["LATITUDE", "LONGITUDE"]].values.tolist()
            if return_to_depot:
                line.append(list(opt.DEPOT))
        folium.PolyLine(line, color=PALETTE[i], weight=1.5, opacity=0.8, dash_array="5, 6").add_to(m)
        for r in g.itertuples():
            ket = getattr(r, "KETERANGAN", "")
            ket = ket if isinstance(ket, str) else ""
            perkiraan = ket.startswith(opt.NO_LONGLAT)
            folium.CircleMarker([r.LATITUDE, r.LONGITUDE], radius=6 if perkiraan else 5, color=PALETTE[i],
                                weight=2 if perkiraan else 1, fill=True,
                                fill_color="white" if perkiraan else PALETTE[i], fill_opacity=0.9,
                                tooltip=f"{s} #{int(r.URUTAN)} — {r.CUSTOMERNO} {r.NAMA_OUTLET or ''}"
                                        + (f"  {ket}" if perkiraan else "")).add_to(m)
    for r in df[df["WEEK"] == opt.UNSCHEDULED].itertuples():
        folium.CircleMarker([r.LATITUDE, r.LONGITUDE], radius=6, color="black",
                            tooltip=f"BELUM TERJADWAL {r.CUSTOMERNO}").add_to(m)
    st_folium(m, height=600, use_container_width=True, returned_objects=[], key=key)


SLOT_OPTS = ["Semua"] + list(opt.build_slots(q_cfg).query("not LIBUR")["SLOT"])

with tab_a:
    pa = st.selectbox("Tampilkan hari", SLOT_OPTS, key="pilih_a")
    jalan_a = road["A"] is not None and st.checkbox("Tampilkan garis jalan sungguhan", value=False,
                                                     disabled=road["A"] is None)
    draw_map(plans["A"], road["A"][0] if jalan_a else None, "map_a", pa)

with tab_b:
    if plans["B"] is None:
        st.info("Plan B belum dibuat. Pastikan API key OpenRouteService sudah diisi di Secrets dan "
                "centang **Buat juga Plan B** di sidebar, lalu klik **🚀 Susun Jadwal** lagi.")
    else:
        pbb = st.selectbox("Tampilkan hari", SLOT_OPTS, key="pilih_b")
        draw_map(plans["B"], road["B"][0], "map_b", pbb)

with tab_edit:
    st.markdown("**Cara revisi:** ubah kolom **Week / Hari** untuk memindah outlet, "
                "atau ubah **Urutan** (boleh 3.5 untuk menyisip di antara 3 dan 4). "
                "Lalu klik salah satu tombol di bawah tabel.")
    with st.form("revisi"):
        edited = st.data_editor(
            plan[[c for c in ["WEEK", "HARI", "URUTAN", "CUSTOMERNO", "NAMA_OUTLET", "ALAMAT", "JARAK_KM",
                              "KUMULATIF_KM", "KETERANGAN"] if c in plan.columns]],
            column_config={
                "WEEK": st.column_config.SelectboxColumn("Week", options=opt.WEEKS + [opt.UNSCHEDULED], required=True),
                "HARI": st.column_config.SelectboxColumn("Hari", options=opt.HARI + [opt.UNSCHEDULED], required=True),
                "URUTAN": st.column_config.NumberColumn("Urutan", min_value=0, step=0.5),
            },
            disabled=["CUSTOMERNO", "NAMA_OUTLET", "ALAMAT", "JARAK_KM", "KUMULATIF_KM", "KETERANGAN"],
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
                    if active == "B" and ors:
                        try:
                            new.loc[sub.index, "URUTAN"] = pb.optimize_slot_road(
                                sub, ors, factor, return_to_depot, time_limit)
                            continue
                        except RoadError as e:
                            st.warning(f"Pakai garis lurus untuk {w}-{h}: {e}")
                    new.loc[sub.index, "URUTAN"] = opt.optimize_slot(sub, factor, return_to_depot, time_limit)
        with st.spinner("Menghitung ulang jarak..."):
            save_plan(opt.compute_distances(new, factor))
        st.rerun()

ret_active = road["B"][1] if active == "B" and road.get("B") else None
ring = opt.summary(plan, q_cfg, factor, return_to_depot, ret_active)

with tab_sum:
    if plans["B"] is not None and road["A"] is not None:
        st.subheader("Perbandingan Plan A vs Plan B")
        rows = []
        for k, nama in [("A", "Plan A (by gruping)"), ("B", "Plan B (by jalan)")]:
            g, r = road[k]
            dfr = pb.apply_road(plans[k], ors, return_to_depot)[0] if k == "A" else plans[k]
            sm = opt.summary(dfr, q_cfg, factor, return_to_depot, r)
            rows.append({"Plan": nama, "Total km jalan (2 minggu)": round(sm["TOTAL_KM"].sum(), 1),
                         "Rata-rata km/hari": round(sm["TOTAL_KM"].sum() / max(1, (sm["JUMLAH_OUTLET"] > 0).sum()), 1)})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption("Km dihitung lewat jalan sungguhan (OpenRouteService) untuk kedua plan.")
    st.subheader(f"Rincian per hari — Plan {active}")
    st.dataframe(ring, hide_index=True, use_container_width=True)
    over = ring[ring["SELISIH"] > 0]
    if len(over):
        st.warning("Hari yang melebihi kuota: " +
                   ", ".join(f"{r.WEEK}-{r.HARI} (+{r.SELISIH})" for r in over.itertuples()))
    label_km = "Total jarak 2 minggu (jalan)" if ret_active is not None else "Total jarak 2 minggu (perkiraan)"
    st.metric(label_km, f"{ring['TOTAL_KM'].sum():,.1f} km")

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
                for k in ("A", "B"):
                    if plans[k] is not None:
                        base_k = plans[k][~plans[k]["CUSTOMERNO"].isin(new["CUSTOMERNO"])]   # buang lokasi perkiraan
                        save_plan(opt.add_outlets(base_k, new.assign(KETERANGAN=""), q_cfg, factor,
                                                  return_to_depot, time_limit), k)
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
    info = {"Salesman": salesman, "Metode": "Plan B (by jalan)" if active == "B" else "Plan A (by gruping)",
            "Kuota/hari": quota, "Kuota Sabtu": quota // 2, "Hari kerja": mode,
            "Hari libur": ", ".join(f"{w}-{h}" for w, h in sorted(off_days)) or "-",
            "Faktor jalan": factor, "Pulang ke titik awal": return_to_depot,
            "Titik awal": f"{opt.DEPOT[0]}, {opt.DEPOT[1]}"}
    st.download_button("📥 Download Excel", data=opt.to_excel_bytes(plan, ring, info),
                       file_name=f"RoutePlan_{salesman or 'salesman'}_Plan{active}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       type="primary")
