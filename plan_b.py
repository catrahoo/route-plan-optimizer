"""Plan B: pembagian hari & urutan kunjungan berdasarkan jarak JALAN (OpenRouteService),
tanpa hitungan "toko terlewati" supaya proses cepat."""
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

import optimizer as opt

PASSBY_M = 30          # toko dianggap "terlewati" bila <= 30 m dari garis rute
UNROUTABLE_PENALTY = 3.0


# ---------- util ----------
def _pts(sub: pd.DataFrame):
    return list(zip(sub["LATITUDE"].astype(float), sub["LONGITUDE"].astype(float)))


def _hav_ab(a, b) -> np.ndarray:
    a, b = np.radians(np.asarray(a, float)), np.radians(np.asarray(b, float))
    dlat = a[:, None, 0] - b[None, :, 0]
    dlon = a[:, None, 1] - b[None, :, 1]
    h = np.sin(dlat / 2) ** 2 + np.cos(a[:, None, 0]) * np.cos(b[None, :, 0]) * np.sin(dlon / 2) ** 2
    return 2 * 6371.0088 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


def road_matrix(ors, a, b, factor) -> np.ndarray:
    """Matrix jarak jalan (km); pasangan yang gagal dirute diganti garis lurus x faktor x penalti."""
    D = ors.matrix(a, b)
    bad = np.isnan(D)
    if bad.any():
        D[bad] = (_hav_ab(a, b) * factor * UNROUTABLE_PENALTY)[bad]
    return D


def _slot_keys(quota):
    return [(s.WEEK, s.HARI) for s in opt.build_slots(quota).itertuples()]


# ---------- matrix lokal: hanya pasangan toko yang berdekatan ----------
def local_matrix(ors, pts, factor, radius_km=1.5, step=None):
    """Jarak jalan (km) untuk pasangan dalam radius ±radius_km (per kotak grid).
    Pasangan yang lebih jauh diisi garis lurus x faktor x 1.5 (cukup untuk pengelompokan)."""
    n = len(pts)
    xy = opt.to_xy([p[0] for p in pts], [p[1] for p in pts])
    hav = _hav_ab(pts, pts)
    D = np.full((n, n), np.nan)
    np.fill_diagonal(D, 0.0)
    # depot <-> semua toko
    D[0:1, :] = road_matrix(ors, pts[:1], pts, factor)
    D[:, 0:1] = road_matrix(ors, pts, pts[:1], factor)
    cell = np.floor(xy[1:] / radius_km).astype(int)
    cells = {}
    for i, c in enumerate(map(tuple, cell)):
        cells.setdefault(c, []).append(i + 1)
    for k, (c, src) in enumerate(cells.items()):
        lo, hi = (np.array(c) - 1) * radius_km, (np.array(c) + 2) * radius_km
        dst = [j for j in range(1, n) if (lo <= xy[j]).all() and (xy[j] < hi).all()]
        sub = road_matrix(ors, [pts[i] for i in src], [pts[j] for j in dst], factor)
        D[np.ix_(src, dst)] = sub
        if step:
            step((k + 1) / len(cells))
    miss = np.isnan(D)
    D[miss] = (hav * factor * 1.5)[miss]
    return D


def _linkage_assign(D, lab, sizes, n_near=None, max_iter=8):
    """Penugasan ulang berkapasitas: biaya toko i ke hari k = rata-rata jarak jalan
    ke toko di hari k (semua toko bila n_near=None -> kelompok padat & sadar jalan)."""
    S = np.minimum(D, D.T)
    np.fill_diagonal(S, np.inf)
    K = len(sizes)
    cols = np.repeat(np.arange(K), sizes)

    def cost_matrix(lb):
        C = np.empty((len(lb), K))
        for k in range(K):
            mem = np.where(lb == k)[0]
            if len(mem) == 0:
                C[:, k] = 1e3
                continue
            part = S[:, mem] if n_near is None else np.sort(S[:, mem], axis=1)[:, :min(n_near, len(mem))]
            part = np.where(np.isinf(part), np.nan, part)
            C[:, k] = np.nan_to_num(np.nanmean(part, axis=1), nan=1e3)
        return C

    def objective(lb):
        C = cost_matrix(lb)
        return C[np.arange(len(lb)), lb].sum()

    best, best_obj = lab.copy(), objective(lab)
    cur = lab.copy()
    for _ in range(max_iter):
        C = cost_matrix(cur)
        r, c = linear_sum_assignment(C[:, cols])
        new = np.full(len(cur), -1)
        new[r] = cols[c]
        ob = objective(new)
        if ob < best_obj - 1e-6:
            best, best_obj, cur = new.copy(), ob, new
        else:
            break
    return best


# ---------- urutan per hari pakai jarak jalan ----------
def optimize_slot_road(sub, ors, factor, return_to_depot, time_limit_s) -> pd.Series:
    pts = [opt.DEPOT] + _pts(sub)
    D = road_matrix(ors, pts, pts, factor)
    order = opt.solve_tsp(D, return_to_depot, time_limit_s)
    urutan = pd.Series(0, index=sub.index)
    urutan.loc[sub.index[np.array(order) - 1]] = np.arange(1, len(order) + 1)
    return urutan


# ---------- jarak per kaki & geometri dari rute jalan ----------
def apply_road(df, ors, return_to_depot):
    """Ganti JARAK_KM/KUMULATIF_KM dengan jarak jalan.
    Return (df, geoms, return_km). geoms[key] = (garis lengkap, garis kunjungan saja)."""
    df = opt.sort_plan(df)
    geoms, ret = {}, {}
    for (w, h), sub in df[df["WEEK"] != opt.UNSCHEDULED].groupby(["WEEK", "HARI"], sort=False):
        pts = [opt.DEPOT] + _pts(sub) + ([opt.DEPOT] if return_to_depot else [])
        legs, geom, wp = ors.route(pts)
        m = len(sub)
        df.loc[sub.index, "JARAK_KM"] = np.round(legs[:m], 2)
        df.loc[sub.index, "KUMULATIF_KM"] = np.round(np.cumsum(legs[:m]), 2)
        ret[(w, h)] = float(legs[m]) if return_to_depot and len(legs) > m else 0.0
        inner = geom[wp[1]:wp[m] + 1] if m >= 2 else []
        geoms[(w, h)] = (geom, inner)
    return df, geoms, ret


# ---------- deteksi toko terlewati ----------
def _xy(latlon) -> np.ndarray:
    a = np.asarray(latlon, float)
    return opt.to_xy(a[:, 0], a[:, 1]) * 1000.0          # meter


def _dist_to_polyline(p_xy, line_xy) -> np.ndarray:
    """Jarak terdekat (m) tiap titik p ke polyline."""
    if len(line_xy) < 2:
        return np.full(len(p_xy), np.inf)
    a, b = line_xy[:-1], line_xy[1:]
    ab = b - a
    L2 = np.maximum((ab ** 2).sum(1), 1e-9)
    best = np.full(len(p_xy), np.inf)
    for i0 in range(0, len(a), 2000):
        A, AB, l2 = a[i0:i0 + 2000], ab[i0:i0 + 2000], L2[i0:i0 + 2000]
        ap = p_xy[:, None, :] - A[None, :, :]
        t = np.clip((ap * AB[None]).sum(2) / l2[None], 0, 1)
        proj = A[None] + t[..., None] * AB[None]
        d = np.sqrt(((p_xy[:, None, :] - proj) ** 2).sum(2)).min(1)
        best = np.minimum(best, d)
    return best


def passby_table(df, geoms) -> pd.DataFrame:
    """Daftar toko yang dilewati rute kunjungan hari lain (<= PASSBY_M).
    Perjalanan berangkat/pulang kantor tidak dihitung."""
    sched = df[df["WEEK"] != opt.UNSCHEDULED]
    if sched.empty:
        return pd.DataFrame(columns=["CUSTOMERNO", "HARI_JADWAL", "DILEWATI_RUTE", "JARAK_M"])
    p = _xy(_pts(sched))
    own = list(zip(sched["WEEK"], sched["HARI"]))
    rows = []
    for key, (_, geom) in geoms.items():
        if len(geom) < 2:
            continue
        d = _dist_to_polyline(p, _xy(geom))
        for i in np.where(d <= PASSBY_M)[0]:
            if own[i] != key:
                rows.append({"CUSTOMERNO": sched.iloc[i]["CUSTOMERNO"],
                             "HARI_JADWAL": f"{own[i][0]} - {own[i][1]}",
                             "DILEWATI_RUTE": f"{key[0]} - {key[1]}", "JARAK_M": round(float(d[i]))})
    t = pd.DataFrame(rows, columns=["CUSTOMERNO", "HARI_JADWAL", "DILEWATI_RUTE", "JARAK_M"])
    return t.sort_values("JARAK_M").drop_duplicates("CUSTOMERNO").reset_index(drop=True)


def _repair(df, geoms, quota, tol, factor, only=None):
    """Pindahkan toko terlewati ke hari yang rutenya melewatinya (atau tukar bila hari itu penuh).
    only = nomor baris tabel terlewati yang dicoba (None = semua sekaligus)."""
    caps = {(s.WEEK, s.HARI): s.CAP + tol for s in opt.build_slots(quota).itertuples()}
    pb = passby_table(df, geoms)
    if pb.empty:
        return df, set()
    df = df.copy()
    slot_of = dict(zip(df["CUSTOMERNO"], zip(df["WEEK"], df["HARI"])))
    count = pd.Series(list(slot_of.values())).value_counts().to_dict()
    pos = df.set_index("CUSTOMERNO")[["LATITUDE", "LONGITUDE"]].astype(float)
    on_route = set(pb["CUSTOMERNO"])
    moved, changed = set(), set()

    def members(key):
        return [c for c, k in slot_of.items() if k == key]

    def nearest_km(code, key, exclude=()):
        m = [c for c in members(key) if c != code and c not in exclude]
        if not m:
            return opt.haversine_matrix([pos.at[code, "LATITUDE"], opt.DEPOT[0]],
                                        [pos.at[code, "LONGITUDE"], opt.DEPOT[1]])[0, 1]
        return float(_hav_ab([pos.loc[code].values], pos.loc[m].values).min())

    rows = pb.itertuples() if only is None else pb.iloc[[only]].itertuples() if only < len(pb) else []
    for r in rows:
        j = r.CUSTOMERNO
        if j in moved:
            continue
        t = slot_of[j]
        s = tuple(r.DILEWATI_RUTE.split(" - "))
        if t[0] == opt.UNSCHEDULED or s == t:
            continue
        if count.get(s, 0) < caps[s]:
            slot_of[j] = s
            count[s] = count.get(s, 0) + 1
            count[t] -= 1
        else:
            # tukar: keluarkan dari hari s toko yang paling "pantas" pindah ke hari t
            best, best_gain = None, None
            for k in members(s):
                if k in moved or k in on_route or k == j:
                    continue
                gain = nearest_km(k, s) - nearest_km(k, t, exclude=(j,))
                if best_gain is None or gain > best_gain:
                    best, best_gain = k, gain
            if best is None or best_gain < -0.3:
                continue
            slot_of[j], slot_of[best] = s, t
            moved.add(best)
        moved.add(j)
        changed |= {s, t}
    df["WEEK"] = df["CUSTOMERNO"].map(lambda c: slot_of[c][0])
    df["HARI"] = df["CUSTOMERNO"].map(lambda c: slot_of[c][1])
    df.loc[df["CUSTOMERNO"].isin(moved), "URUTAN"] = 9999
    return df, changed


def _score(df, geoms, ret, quota, factor, return_to_depot):
    km = opt.summary(df, quota, factor, return_to_depot, ret)["TOTAL_KM"].sum()
    return len(passby_table(df, geoms)), km


# ---------- rangkaian lengkap Plan B ----------
def build_plan_b(plan_a, ors, quota, factor, return_to_depot, time_limit_s=2, tol=0, step=None):
    step = step or (lambda msg, p: None)
    df = plan_a.copy()
    keys = _slot_keys(quota)
    sched = df[df["WEEK"] != opt.UNSCHEDULED]
    if sched.empty:
        df, geoms, ret = apply_road(df, ors, return_to_depot)
        return df, geoms, ret
    idx = sched.index.to_numpy()
    pts = np.array(_pts(sched))
    lab = np.array([keys.index(k) for k in zip(sched["WEEK"], sched["HARI"])])
    sizes = np.bincount(lab, minlength=len(keys))

    # 1) matrix jarak jalan antar toko yang berdekatan (hemat kuota API)
    step("Mengambil jarak jalan antar toko...", 0.05)
    allpts = [tuple(opt.DEPOT)] + [tuple(p) for p in pts]
    D = local_matrix(ors, allpts, factor, step=lambda p: step("Mengambil jarak jalan antar toko...", 0.05 + 0.4 * p))
    pos = {c: i + 1 for i, c in enumerate(sched["CUSTOMERNO"])}

    # 2) bagi hari: tiap toko dikumpulkan dengan tetangga terdekatnya lewat jalan (kuota tetap)
    step("Membagi hari berdasarkan jarak jalan...", 0.5)
    lab = _linkage_assign(D[1:, 1:], lab, sizes)
    df.loc[idx, "WEEK"] = [keys[k][0] for k in lab]
    df.loc[idx, "HARI"] = [keys[k][1] for k in lab]

    def reorder(frame, keys_to_do):
        for key in keys_to_do:
            sub = frame[(frame["WEEK"] == key[0]) & (frame["HARI"] == key[1])]
            if len(sub):
                ii = [0] + [pos[c] for c in sub["CUSTOMERNO"]]
                order = opt.solve_tsp(D[np.ix_(ii, ii)], return_to_depot, time_limit_s)
                u = pd.Series(0, index=sub.index)
                u.loc[sub.index[np.array(order) - 1]] = np.arange(1, len(order) + 1)
                frame.loc[sub.index, "URUTAN"] = u
        return frame

    # urutan kunjungan tiap hari pakai jarak jalan
    step("Menyusun urutan rute tiap hari...", 0.6)
    df = reorder(df, set(zip(df.loc[idx, "WEEK"], df.loc[idx, "HARI"])))
    df = opt.compute_distances(df, factor)

    # 3) ambil garis rute jalan & jarak per kaki
    step("Mengambil garis rute jalan...", 0.7)
    df, geoms, ret = apply_road(df, ors, return_to_depot)
    step("Selesai", 1.0)
    return df, geoms, ret
