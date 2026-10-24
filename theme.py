"""Tampilan: tema hijau bergradasi, header, dan ikon garis (SVG buatan sendiri)."""
import streamlit as st

GREEN_1 = "#2BB673"
GREEN_2 = "#0B7A3E"

_ICON = {  # ikon garis 24x24, stroke mengikuti warna teks
    "paste": '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4.5V3h6v1.5"/><path d="M9 10h6M9 14h6M9 18h4"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/><path d="M8 14h2M12 14h2M16 14h0.5M8 17.5h2M12 17.5h2"/>',
    "route": '<circle cx="6" cy="18" r="2.2"/><circle cx="18" cy="6" r="2.2"/><path d="M8.2 18H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.8" stroke-dasharray="2.2 2.2"/>',
    "map": '<path d="M9 4 3.5 6v14L9 18l6 2 5.5-2V4L15 6 9 4Z"/><path d="M9 4v14M15 6v14"/>',
    "edit": '<path d="M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17v3Z"/><path d="M14.5 7.5l3 3"/>',
    "download": '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5"/><path d="M4.5 16.5V19a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5v-2.5"/>',
    "pin": '<path d="M12 21s-6.5-6.2-6.5-11a6.5 6.5 0 0 1 13 0c0 4.8-6.5 11-6.5 11Z"/><circle cx="12" cy="10" r="2.4"/>',
}


def icon(name: str, size: int = 34) -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">{_ICON[name]}</svg>')


def inject():
    st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Raleway:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, .stTextInput, .stNumberInput, .stRadio, .stCheckbox, button {{
  font-family: 'Raleway', sans-serif;
}}
.block-container {{ padding-top: 1.2rem; max-width: 1300px; }}

/* Header */
.rp-hero {{
  position: relative; overflow: hidden; border-radius: 14px; padding: 34px 38px 30px;
  background: linear-gradient(120deg, #F3F5F4 0%, #E9EEEB 100%);
  border: 1px solid #E1E7E3; margin-bottom: 0;
}}
.rp-hero h1 {{
  font-family: 'DM Serif Display', serif; font-weight: 400; font-size: 2.6rem; line-height: 1.1;
  color: #16201B; margin: 0 0 10px; padding: 0;
}}
.rp-hero p {{ color: #47544D; font-size: 1rem; margin: 0; max-width: 560px; }}
.rp-hero .rp-badge {{
  display: inline-block; font-size: .72rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase;
  color: {GREEN_2}; margin-bottom: 10px;
}}
.rp-hero .rp-art {{ position: absolute; right: 34px; top: 50%; transform: translateY(-50%); opacity: .95; }}
@media (max-width: 900px) {{ .rp-hero .rp-art {{ display: none; }} .rp-hero h1 {{ font-size: 2rem; }} }}

/* Strip langkah kerja */
.rp-strip {{
  display: grid; grid-template-columns: repeat(6, 1fr); border-radius: 0 0 14px 14px; overflow: hidden;
  background: linear-gradient(90deg, {GREEN_1} 0%, {GREEN_2} 100%); margin: -8px 0 22px; color: #fff;
}}
.rp-strip div {{
  padding: 18px 8px 14px; text-align: center; border-right: 1px solid rgba(255,255,255,.18);
  font-size: .74rem; font-weight: 600; letter-spacing: .08em; text-transform: uppercase;
}}
.rp-strip div:last-child {{ border-right: none; }}
.rp-strip svg {{ display: block; margin: 0 auto 8px; }}
@media (max-width: 900px) {{ .rp-strip {{ grid-template-columns: repeat(3, 1fr); }} }}

/* Tombol */
.stButton > button[kind="primary"], div[data-testid="stDownloadButton"] button,
div[data-testid="stFormSubmitButton"] button {{
  background: linear-gradient(90deg, {GREEN_1}, {GREEN_2}); color: #fff; border: none;
  border-radius: 4px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; padding: .55rem 1.4rem;
}}
.stButton > button[kind="primary"]:hover, div[data-testid="stDownloadButton"] button:hover,
div[data-testid="stFormSubmitButton"] button:hover {{ filter: brightness(1.07); color: #fff; }}

/* Tab */
button[data-baseweb="tab"] {{ font-weight: 600; }}
button[data-baseweb="tab"][aria-selected="true"] {{ color: {GREEN_2}; }}
div[data-baseweb="tab-highlight"] {{ background: {GREEN_1}; }}

/* Kartu angka */
div[data-testid="stMetric"] {{
  background: #fff; border: 1px solid #E4EAE6; border-left: 4px solid {GREEN_1};
  border-radius: 8px; padding: 12px 16px;
}}
div[data-testid="stMetricLabel"] p {{ font-size: .78rem; text-transform: uppercase; letter-spacing: .06em; color: #5C6A62; }}

/* Sidebar */
section[data-testid="stSidebar"] > div {{ background: linear-gradient(180deg, #FFFFFF 0%, #EEF4F0 100%); }}
section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 {{
  font-family: 'DM Serif Display', serif; font-weight: 400; color: #16201B;
}}
.rp-credit {{ font-size: .75rem; color: #6B7A71; }}
</style>
""", unsafe_allow_html=True)


def _art() -> str:
    """Ilustrasi sederhana: kartu peta dengan rute putus-putus dan pin."""
    return f"""
<svg class="rp-art" width="300" height="150" viewBox="0 0 300 150" fill="none">
  <rect x="20" y="8" width="262" height="134" rx="10" fill="#fff" stroke="#DCE4DF"/>
  <rect x="34" y="22" width="70" height="8" rx="4" fill="#E6ECE8"/>
  <rect x="200" y="22" width="68" height="8" rx="4" fill="#E6ECE8"/>
  <path d="M50 118 C 90 118, 80 70, 125 72 S 170 112, 205 92 S 240 48, 262 52"
        stroke="{GREEN_1}" stroke-width="2.4" stroke-dasharray="6 6" stroke-linecap="round"/>
  <circle cx="50" cy="118" r="7" fill="{GREEN_2}"/>
  <circle cx="125" cy="72" r="5.5" fill="#fff" stroke="{GREEN_1}" stroke-width="2.4"/>
  <circle cx="205" cy="92" r="5.5" fill="#fff" stroke="{GREEN_1}" stroke-width="2.4"/>
  <path d="M262 64s-11-10.5-11-18.6a11 11 0 0 1 22 0c0 8.1-11 18.6-11 18.6Z" fill="{GREEN_2}"/>
  <circle cx="262" cy="45.5" r="4" fill="#fff"/>
</svg>"""


def header():
    st.markdown(f"""
<div class="rp-hero">
  <div class="rp-badge">Route Plan Optimizer</div>
  <h1>Rute lebih rapi.<br>Kunjungan lebih efisien.</h1>
  <p>Copas kode customer, jadwal kunjungan 2 minggu tersusun otomatis
     berdasarkan kedekatan lokasi dan jalan yang dilalui.</p>
  {_art()}
</div>
<div class="rp-strip">
  <div>{icon("paste")}Copas Kode</div>
  <div>{icon("calendar")}Bagi Hari</div>
  <div>{icon("route")}Rute Jalan</div>
  <div>{icon("map")}Peta</div>
  <div>{icon("edit")}Revisi</div>
  <div>{icon("download")}Download</div>
</div>
""", unsafe_allow_html=True)
