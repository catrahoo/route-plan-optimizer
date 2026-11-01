"""Test fungsi inti optimizer (tanpa Supabase, tanpa Streamlit)."""
import numpy as np
import pandas as pd

import optimizer as opt


def test_parse_gmaps_normal_dan_tertukar():
    assert opt.parse_gmaps("-7.2592, 112.6936") == (-7.2592, 112.6936)
    assert opt.parse_gmaps("112.6936, -7.2592") == (-7.2592, 112.6936)
    assert opt.parse_gmaps("-7,2592 112,6936") == (-7.2592, 112.6936)
    assert opt.parse_gmaps("") == (None, None)


def test_valid_coord_hanya_surabaya_raya():
    hasil = opt.valid_coord([-7.26, -6.2, None], [112.7, 106.8, 112.7]).tolist()
    assert hasil == [True, False, False]


def test_kapasitas_sabtu_setengah_dan_hari_libur():
    assert opt.capacity(20) == 2 * (5 * 20 + 10)
    libur = (20, {("Ganjil", "Senin")})
    assert opt.capacity(libur) == opt.capacity(20) - 20


def test_target_sizes_jumlahnya_pas():
    caps = opt.build_slots(20)["CAP"]
    for n in (0, 7, 100, 219):
        assert opt.target_sizes(n, caps).sum() == n


def test_haversine_simetris_dan_jarak_wajar():
    lat = [-7.2575, -7.2905]   # Tugu Pahlawan, Bungurasih (kira-kira)
    lon = [112.7378, 112.7270]
    d = opt.haversine_matrix(lat, lon)
    assert np.allclose(d, d.T)
    assert np.allclose(np.diag(d), 0)
    assert 3 < d[0, 1] < 5


def test_build_plan_semua_outlet_terjadwal_dan_urutan_rapi():
    rng = np.random.default_rng(0)
    n = 60
    outlets = pd.DataFrame({
        "CUSTOMERNO": [f"C{i:03d}" for i in range(n)],
        "LATITUDE": -7.26 + rng.uniform(-0.05, 0.05, n),
        "LONGITUDE": 112.70 + rng.uniform(-0.05, 0.05, n),
    })
    plan = opt.build_plan(outlets, quota=10, mode=None, factor=1.3,
                          return_to_depot=True, time_limit_s=1)

    assert len(plan) == n
    assert set(plan["CUSTOMERNO"]) == set(outlets["CUSTOMERNO"])
    assert (plan["WEEK"] != opt.UNSCHEDULED).all()

    slots = opt.build_slots(10).set_index("SLOT")["CAP"]
    for slot, sub in plan.groupby("SLOT"):
        assert len(sub) <= slots[slot]
        assert sorted(sub["URUTAN"]) == list(range(1, len(sub) + 1))
    assert (plan["JARAK_KM"] >= 0).all()
