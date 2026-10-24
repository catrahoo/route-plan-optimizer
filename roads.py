"""Jarak & rute lewat jalan sungguhan memakai OpenRouteService (api.heigit.org)."""
import json
import time
import urllib.error
import urllib.request

import numpy as np

BASE = "https://api.heigit.org/openrouteservice/v2"
PROFILE = "driving-car"
MAX_ROUTES = 3500          # batas sel matrix per permintaan
MAX_WAYPOINTS = 50         # batas titik per permintaan directions
MIN_GAP_S = 1.6            # ±37 permintaan/menit (batas 40/menit)


class RoadError(Exception):
    pass


class ORS:
    def __init__(self, key: str, log=None):
        self.key = key.strip()
        self.log = log or (lambda msg: None)
        self._last = 0.0
        self._mcache = {}
        self._rcache = {}
        self.n_matrix = 0
        self.n_directions = 0

    # ---------- HTTP ----------
    def _post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        for attempt in range(4):
            wait = MIN_GAP_S - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            req = urllib.request.Request(BASE + path, data=data, method="POST", headers={
                "Authorization": self.key, "Content-Type": "application/json",
                "Accept": "application/json, application/geo+json"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                txt = e.read().decode(errors="ignore")[:300]
                if e.code == 429:
                    if "quota" in txt.lower() or "daily" in txt.lower():
                        raise RoadError("Kuota harian OpenRouteService habis. Coba lagi besok atau pakai Plan A.")
                    self.log("Server sibuk, menunggu 60 detik...")
                    time.sleep(60)
                    continue
                if e.code in (401, 403):
                    raise RoadError("API key OpenRouteService tidak valid. Cek isi [ors] key di Secrets.")
                if e.code >= 500 and attempt < 3:
                    time.sleep(5)
                    continue
                raise RoadError(f"OpenRouteService error {e.code}: {txt}")
            except urllib.error.URLError as e:
                if attempt < 3:
                    time.sleep(5)
                    continue
                raise RoadError(f"Tidak bisa terhubung ke OpenRouteService: {e.reason}")
        raise RoadError("OpenRouteService tidak merespons setelah beberapa kali dicoba.")

    # ---------- Matrix ----------
    def matrix(self, src, dst) -> np.ndarray:
        """Jarak jalan (km) dari tiap titik src ke tiap titik dst. Titik = (lat, lon).
        Pasangan yang tidak bisa dirute -> NaN."""
        src = [tuple(map(float, p)) for p in src]
        dst = [tuple(map(float, p)) for p in dst]
        out = np.full((len(src), len(dst)), np.nan)
        todo_s = [i for i in range(len(src))]
        # potong jadi blok yang muat 3500 sel
        bs = max(1, min(len(src), MAX_ROUTES // max(1, min(len(dst), MAX_ROUTES))))
        bd = max(1, min(len(dst), MAX_ROUTES // bs))
        for i0 in range(0, len(todo_s), bs):
            si = todo_s[i0:i0 + bs]
            for j0 in range(0, len(dst), bd):
                dj = list(range(j0, min(j0 + bd, len(dst))))
                key = (tuple(src[i] for i in si), tuple(dst[j] for j in dj))
                if key not in self._mcache:
                    locs = [[p[1], p[0]] for p in key[0]] + [[p[1], p[0]] for p in key[1]]
                    res = self._post(f"/matrix/{PROFILE}", {
                        "locations": locs,
                        "sources": list(range(len(si))),
                        "destinations": list(range(len(si), len(si) + len(dj))),
                        "metrics": ["distance"], "units": "km"})
                    self.n_matrix += 1
                    self._mcache[key] = np.array(
                        [[np.nan if v is None else v for v in row] for row in res["distances"]], float)
                out[np.ix_(si, dj)] = self._mcache[key]
        return out

    # ---------- Directions ----------
    def route(self, points):
        """Rute lewat jalan melalui titik-titik berurutan (lat, lon).
        Return: (jarak per kaki km [len-1], geometri [(lat, lon), ...],
                 indeks geometri tiap titik [len])."""
        points = [tuple(map(float, p)) for p in points]
        key = tuple(points)
        if key in self._rcache:
            return self._rcache[key]
        legs, geom, wp = [], [], []
        step = MAX_WAYPOINTS - 1
        for a in range(0, len(points) - 1, step):
            chunk = points[a:a + step + 1]
            res = self._post(f"/directions/{PROFILE}/geojson", {
                "coordinates": [[p[1], p[0]] for p in chunk],
                "radiuses": [-1] * len(chunk), "units": "km",
                "instructions": False})
            self.n_directions += 1
            feat = res["features"][0]
            segs = feat["properties"].get("segments", [])
            legs += [s.get("distance", 0.0) for s in segs]
            g = [(c[1], c[0]) for c in feat["geometry"]["coordinates"]]
            w = feat["properties"].get("way_points") or [0] * (len(chunk) - 1) + [len(g) - 1]
            off = len(geom) - 1 if geom else 0
            wp += [off + x for x in (w if not wp else w[1:])]
            geom += g if not geom else g[1:]
        if len(legs) != len(points) - 1:   # jaga-jaga titik yang identik digabung server
            legs = (legs + [0.0] * len(points))[:len(points) - 1]
        wp = (wp + [len(geom) - 1] * len(points))[:len(points)]
        self._rcache[key] = (legs, geom, wp)
        return legs, geom, wp
