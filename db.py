import pandas as pd
import streamlit as st
from supabase import create_client

COLS = ["customerno", "nama_outlet", "salesman", "alamat", "sales_office",
        "sales_group", "sales_district", "latitude", "longitude"]


@st.cache_resource
def get_client():
    s = st.secrets["supabase"]
    return create_client(s["url"], s["key"])


@st.cache_data(ttl=600, show_spinner=False)
def fetch_outlets(codes: tuple) -> pd.DataFrame:
    """Ambil data outlet dari Supabase berdasarkan daftar CUSTOMERNO."""
    sb, rows, codes = get_client(), [], list(codes)
    for i in range(0, len(codes), 500):
        rows += sb.rpc("get_outlets", {"codes": codes[i:i + 500]}).execute().data
    df = pd.DataFrame(rows, columns=COLS)
    return df.rename(columns=str.upper)
