import math
from io import BytesIO

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

DEPOT = (-7.259280093018434, 112.69361822224205)
HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"]
WEEKS = ["Ganjil", "Genap"]
UNSCHEDULED = "BELUM TERJADWAL"
# Batas wilayah kerja (Surabaya Raya) untuk cek koordinat wajar
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = -7.65, -7.0, 112.4, 113.0


def valid_coord(lat, lon) -> pd.Series:
    lat = pd.to_numeric(pd.Series(lat), errors="coerce")
    lon = pd.to_numeric(pd.Series(lon), errors="coerce")
    return (lat.between(LAT_MIN, LAT_MAX) & lon.between(LON_MIN, LON_MAX)).fillna(False)


def parse_gmaps(text):
    """'-7.2592, 112.6936' (copy dari Google Maps) -> (lat, lon) atau (None, None)."""
    import re
    angka = re.findall(r"-?\d+(?:[.,]\d+)?", str(text or ""))
    if len(angka) < 2:
        return None, None
    a, b = (float(x.replace(",", ".")) for x in angka[:2])
    if abs(a) > 90:          # tertukar (long, lat)
        a, b = b, a
    return a, b


# ---------- Kapasitas ----------
def build_slots(quota: int) -> pd.DataFrame:
    sat = quota // 2
    rows = [{"WEEK": w, "HARI": h, "CAP": sat if h == "Sabtu" else quota}
            for w in WEEKS for h in HARI]
    df = pd.DataFrame(rows)
    df["SLOT"] = df["WEEK"] + " - " + df["HARI"]
    return df


def capacity(quota: int) -> int:
    return int(build_slots(quota)["CAP"].sum())


def target_sizes(n: int, caps) -> np.ndarray:
    """Bagi n ke slot sebanding kapasitas (metode sisa terbesar)."""
    caps = np.asarray(caps, dtype=float)
    raw = n * caps / caps.sum()
    base = np.floor(raw).astype(int)
    rem = n - base.sum()
    base[np.argsort(-(raw - base))[:rem]] += 1
    return base


def slot_sizes(n: int, caps, mode: str) -> np.ndarray:
    caps = np.asarray(caps, dtype=int)
    if mode == "Batasi kuota" and n >= caps.sum():
        return caps.copy()
    return target_sizes(n, caps)


# ---------- Geometri ----------
def to_xy(lat, lon) -> np.ndarray:
    k = math.cos(math.radians(DEPOT[0]))
    x = (np.asarray(lon, float) - DEPOT[1]) * 111.320 * k
    y = (np.asarray(lat, float) - DEPOT[0]) * 110.574
    return np.column_stack([x, y])


def haversine_matrix(lat, lon) -> np.ndarray:
    lat = np.radians(np.asarray(lat, float))
    lon = np.radians(np.asarray(lon, float))
    dlat = lat[:, None] - lat[None, :]
    dlon = lon[:, None] - lon[None, :]
    a = np.sin(dlat / 2) ** 2 + np.cos(lat[:, None]) * np.cos(lat[None, :]) * np.sin(dlon / 2) ** 2
    return 2 * 6371.0088 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


# ---------- Tahap A: bagi outlet ke 12 hari ----------
def sweep_labels(xy: np.ndarray, sizes) -> np.ndarray:
    n = len(xy)
    ang = np.arctan2(xy[:, 1], xy[:, 0])
    order = np.argsort(ang)
    a = ang[order]
    gaps = np.diff(np.r_[a, a[0] + 2 * np.pi])
    order = np.roll(order, -((np.argmax(gaps) + 1) % n))
    labels = np.full(n, -1)
    start = 0
    for k, s in enumerate(sizes):
        labels[order[start:start + s]] = k
        start += s
    return labels


def capacitated_assign(xy, centers, sizes) -> np.ndarray:
    cols = np.repeat(np.arange(len(sizes)), sizes)
    cost = ((xy[:, None, :] - centers[cols][None, :, :]) ** 2).sum(axis=2)
    r, c = linear_sum_assignment(cost)
    labels = np.full(len(xy), -1)
    labels[r] = cols[c]
    return labels


def cluster_days(xy, sizes, max_iter: int = 20) -> np.ndarray:
    labels = sweep_labels(xy, sizes)
    for _ in range(max_iter):
        centers = np.array([xy[labels == k].mean(axis=0) if (labels == k).any() else xy.mean(axis=0)
                            for k in range(len(sizes))])
        new = capacitated_assign(xy, centers, sizes)
        if np.array_equal(new, labels):
            break
        labels = new
    return labels


# ---------- Tahap B: urutan kunjungan per hari ----------
def nn_2opt(dist: np.ndarray, return_to_depot: bool = True) -> list:
    n = len(dist)
    unvisited, route, cur = set(range(1, n)), [0], 0
    while unvisited:
        nxt = min(unvisited, key=lambda j: dist[cur, j])
        route.append(nxt)
        unvisited.remove(nxt)
        cur = nxt
    if return_to_depot:
        route.append(0)
    last = len(route) - 2 if return_to_depot else len(route) - 1
    improved = True
    while improved:
        improved = False
        for i in range(1, last):
            for k in range(i + 1, last + 1):
                a, b, c = route[i - 1], route[i], route[k]
                if k + 1 < len(route):
                    d = route[k + 1]
                    delta = dist[a, c] + dist[b, d] - dist[a, b] - dist[c, d]
                else:
                    delta = dist[a, c] - dist[a, b]
                if delta < -1e-9:
                    route[i:k + 1] = route[i:k + 1][::-1]
                    improved = True
    return [x for x in route if x != 0]


def solve_tsp(dist_km: np.ndarray, return_to_depot: bool = True, time_limit_s: int = 2) -> list:
    n = len(dist_km)
    if n <= 3:
        return nn_2opt(dist_km, return_to_depot)
    try:
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    except ImportError:
        return nn_2opt(dist_km, return_to_depot)
    D = np.rint(dist_km * 1000).astype(int)
    if not return_to_depot:
        D[:, 0] = 0
    D = D.tolist()
    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)
    cb = routing.RegisterTransitCallback(lambda i, j: D[manager.IndexToNode(i)][manager.IndexToNode(j)])
    routing.SetArcCostEvaluatorOfAllVehicles(cb)
    p = pywrapcp.DefaultRoutingSearchParameters()
    p.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    p.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    p.time_limit.seconds = int(time_limit_s)
    sol = routing.SolveWithParameters(p)
    if sol is None:
        return nn_2opt(dist_km, return_to_depot)
    order, idx = [], sol.Value(routing.NextVar(routing.Start(0)))
    while not routing.IsEnd(idx):
        order.append(manager.IndexToNode(idx))
        idx = sol.Value(routing.NextVar(idx))
    return order


def optimize_slot(sub: pd.DataFrame, factor: float, return_to_depot: bool, time_limit_s: int) -> pd.Series:
    lat = np.r_[DEPOT[0], sub["LATITUDE"].to_numpy(float)]
    lon = np.r_[DEPOT[1], sub["LONGITUDE"].to_numpy(float)]
    order = solve_tsp(haversine_matrix(lat, lon) * factor, return_to_depot, time_limit_s)
    urutan = pd.Series(0, index=sub.index)
    urutan.loc[sub.index[np.array(order) - 1]] = np.arange(1, len(order) + 1)
    return urutan


# ---------- Rangkaian lengkap ----------
def build_plan(outlets: pd.DataFrame, quota: int, mode: str, factor: float,
               return_to_depot: bool, time_limit_s: int = 2, progress=None) -> pd.DataFrame:
    slots = build_slots(quota)
    df = outlets.reset_index(drop=True).copy()
    sizes = slot_sizes(len(df), slots["CAP"], mode)
    labels = cluster_days(to_xy(df["LATITUDE"], df["LONGITUDE"]), sizes)
    df["WEEK"] = [slots.at[k, "WEEK"] if k >= 0 else UNSCHEDULED for k in labels]
    df["HARI"] = [slots.at[k, "HARI"] if k >= 0 else UNSCHEDULED for k in labels]
    df["URUTAN"] = 0.0
    groups = list(df[df["WEEK"] != UNSCHEDULED].groupby(["WEEK", "HARI"]))
    for i, (_, sub) in enumerate(groups):
        df.loc[sub.index, "URUTAN"] = optimize_slot(sub, factor, return_to_depot, time_limit_s)
        if progress:
            progress((i + 1) / len(groups))
    return compute_distances(df, factor)


def empty_plan(columns) -> pd.DataFrame:
    cols = list(columns) + ["WEEK", "HARI", "URUTAN", "JARAK_KM", "KUMULATIF_KM", "SLOT"]
    return pd.DataFrame(columns=cols)


def add_outlets(plan: pd.DataFrame, new: pd.DataFrame, quota: int, factor: float,
                return_to_depot: bool, time_limit_s: int = 2) -> pd.DataFrame:
    """Masukkan outlet baru ke hari terdekat yang masih ada sisa kuota, lalu rapikan rutenya."""
    slots = build_slots(quota)
    df = plan.copy()
    sched = df[df["WEEK"] != UNSCHEDULED]
    count = sched.groupby(["WEEK", "HARI"]).size().to_dict()
    centers = sched.groupby(["WEEK", "HARI"])[["LATITUDE", "LONGITUDE"]].mean()
    touched, rows = set(), []
    for _, r in new.iterrows():
        best, best_d, best_full = None, None, None
        for s in slots.itertuples():
            key = (s.WEEK, s.HARI)
            if key in centers.index:
                c = centers.loc[key]
                d = haversine_matrix([r.LATITUDE, c.LATITUDE], [r.LONGITUDE, c.LONGITUDE])[0, 1]
            else:
                d = haversine_matrix([r.LATITUDE, DEPOT[0]], [r.LONGITUDE, DEPOT[1]])[0, 1]
            if count.get(key, 0) < s.CAP and (best_d is None or d < best_d):
                best, best_d = key, d
            if best_full is None or d < best_full[1]:
                best_full = (key, d)
        key = best or best_full[0]
        count[key] = count.get(key, 0) + 1
        touched.add(key)
        row = r.to_dict()
        row.update({"WEEK": key[0], "HARI": key[1], "URUTAN": 9999})
        rows.append(row)
    df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
    df["URUTAN"] = pd.to_numeric(df["URUTAN"], errors="coerce").fillna(9999)
    for w, h in touched:
        sub = df[(df["WEEK"] == w) & (df["HARI"] == h)]
        df.loc[sub.index, "URUTAN"] = optimize_slot(sub, factor, return_to_depot, time_limit_s)
    return compute_distances(df, factor)


def sort_plan(df: pd.DataFrame) -> pd.DataFrame:
    w = pd.Categorical(df["WEEK"], WEEKS + [UNSCHEDULED], ordered=True)
    h = pd.Categorical(df["HARI"], HARI + [UNSCHEDULED], ordered=True)
    return (df.assign(_w=w, _h=h).sort_values(["_w", "_h", "URUTAN"])
              .drop(columns=["_w", "_h"]).reset_index(drop=True))


def compute_distances(df: pd.DataFrame, factor: float) -> pd.DataFrame:
    """Rapikan urutan jadi 1..m per hari lalu hitung jarak tiap perpindahan."""
    df = sort_plan(df)
    df["URUTAN"] = 0
    df["JARAK_KM"] = np.nan
    df["KUMULATIF_KM"] = np.nan
    for _, sub in df[df["WEEK"] != UNSCHEDULED].groupby(["WEEK", "HARI"], sort=False):
        lat = np.r_[DEPOT[0], sub["LATITUDE"].to_numpy(float)]
        lon = np.r_[DEPOT[1], sub["LONGITUDE"].to_numpy(float)]
        seg = [haversine_matrix(lat[i:i + 2], lon[i:i + 2])[0, 1] * factor for i in range(len(sub))]
        df.loc[sub.index, "URUTAN"] = np.arange(1, len(sub) + 1)
        df.loc[sub.index, "JARAK_KM"] = np.round(seg, 2)
        df.loc[sub.index, "KUMULATIF_KM"] = np.round(np.cumsum(seg), 2)
    df["SLOT"] = df["WEEK"] + " - " + df["HARI"]
    return df


def summary(df: pd.DataFrame, quota: int, factor: float, return_to_depot: bool,
            return_km: dict = None) -> pd.DataFrame:
    rows = []
    for s in build_slots(quota).itertuples():
        sub = df[(df["WEEK"] == s.WEEK) & (df["HARI"] == s.HARI)].sort_values("URUTAN")
        km = sub["JARAK_KM"].sum()
        if return_to_depot and len(sub) and return_km is not None:
            km += return_km.get((s.WEEK, s.HARI), 0.0)
        elif return_to_depot and len(sub):
            last = sub.iloc[-1]
            km += haversine_matrix([last.LATITUDE, DEPOT[0]], [last.LONGITUDE, DEPOT[1]])[0, 1] * factor
        rows.append({"WEEK": s.WEEK, "HARI": s.HARI, "KUOTA": s.CAP, "JUMLAH_OUTLET": len(sub),
                     "SELISIH": len(sub) - s.CAP, "TOTAL_KM": round(km, 1)})
    return pd.DataFrame(rows)


EXPORT_COLS = ["WEEK", "HARI", "URUTAN", "CUSTOMERNO", "NAMA_OUTLET", "ALAMAT", "SALES_DISTRICT",
               "LATITUDE", "LONGITUDE", "JARAK_KM", "KUMULATIF_KM"]


def to_excel_bytes(plan: pd.DataFrame, ringkasan: pd.DataFrame, info: dict) -> bytes:
    plan = plan[[c for c in EXPORT_COLS if c in plan.columns]]
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as xw:
        plan.to_excel(xw, sheet_name="Route Plan", index=False)
        for w in WEEKS:
            plan[plan["WEEK"] == w].to_excel(xw, sheet_name=f"Week {w}", index=False)
        if (plan["WEEK"] == UNSCHEDULED).any():
            plan[plan["WEEK"] == UNSCHEDULED].to_excel(xw, sheet_name="Belum Terjadwal", index=False)
        ringkasan.to_excel(xw, sheet_name="Ringkasan", index=False)
        pd.DataFrame(list(info.items()), columns=["Parameter", "Nilai"]).to_excel(
            xw, sheet_name="Parameter", index=False)
        for ws in xw.sheets.values():
            ws.freeze_panes(1, 0)
            ws.set_column(0, 12, 16)
        xw.sheets["Route Plan"].autofilter(0, 0, len(plan), len(plan.columns) - 1)
    return buf.getvalue()
