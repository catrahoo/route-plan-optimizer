import pandas as pd
import streamlit as st
from supabase import create_client

COLS = ["customerno", "nama_outlet", "salesman", "alamat", "sales_office",
        "sales_group", "sales_district", "latitude", "longitude"]


def _read_secrets():
    """Baca URL & key Supabase dari Secrets (toleran beberapa format penulisan)."""
    flat = {}
    for k, v in st.secrets.items():
        if hasattr(v, "items"):
            for k2, v2 in v.items():
                flat[f"{k}.{k2}".lower()] = v2
        else:
            flat[k.lower()] = v
    url = next((flat[k] for k in ("supabase.url", "supabase_url", "url") if k in flat), None)
    key = next((flat[k] for k in ("supabase.key", "supabase_key", "key",
                                   "supabase.secret_key", "supabase.service_role_key") if k in flat), None)
    if not url or not key:
        st.error(
            "❌ Secrets Supabase belum benar.\n\n"
            f"Yang terbaca di Secrets sekarang: `{', '.join(sorted(flat)) or '(kosong)'}`\n\n"
            "Buka **Manage app → ⋮ → Settings → Secrets**, hapus semua isinya, lalu paste persis seperti ini:\n\n"
            "```\nAPP_PASSWORD = \"password-tim\"\n\n[supabase]\n"
            "url = \"https://xxxx.supabase.co\"\nkey = \"sb_secret_xxxx\"\n```")
        st.stop()
    return str(url).strip().rstrip("/"), str(key).strip()


@st.cache_resource
def get_client():
    url, key = _read_secrets()
    return create_client(url, key)


@st.cache_data(ttl=600, show_spinner=False)
def fetch_outlets(codes: tuple) -> pd.DataFrame:
    """Ambil data outlet dari Supabase berdasarkan daftar CUSTOMERNO."""
    sb, rows, codes = get_client(), [], list(codes)
    for i in range(0, len(codes), 500):
        try:
            rows += sb.rpc("get_outlets", {"codes": codes[i:i + 500]}).execute().data
        except Exception as e:
            info = getattr(e, "args", [None])[0]
            info = info if isinstance(info, dict) else {"message": str(e)}
            kode, pesan = str(info.get("code", "")), str(info.get("message", ""))
            if kode == "42501" or "permission denied" in pesan.lower():
                saran = "Key yang dipakai salah. Pakai **Secret key** (`sb_secret_...`), bukan Publishable/anon key."
            elif kode == "PGRST202" or "could not find" in pesan.lower():
                saran = "Fungsi `get_outlets` belum ada. Jalankan ulang file SQL di Supabase > SQL Editor."
            elif "api key" in pesan.lower() or kode in ("401", "PGRST301"):
                saran = "API key tidak valid. Cek lagi isi `key` di Secrets Streamlit (jangan ada spasi/tanda kutip ganda)."
            else:
                saran = "Kirim pesan error ini ke pembuat aplikasi."
            st.error(f"❌ Gagal mengambil data dari Supabase.\n\n**Kode:** {kode}  \n**Pesan:** {pesan}\n\n💡 {saran}")
            st.stop()
    df = pd.DataFrame(rows, columns=COLS)
    return df.rename(columns=str.upper)
