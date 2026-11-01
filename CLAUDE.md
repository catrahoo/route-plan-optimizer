# Route Plan Optimizer

Aplikasi Streamlit untuk menyusun jadwal kunjungan outlet salesman selama 2 minggu (Ganjil/Genap, Senin–Sabtu) dan mengurutkan rute per hari. Data outlet ada di Supabase. Hasil bisa diunduh sebagai Excel.

## Struktur
- `app.py`: tampilan Streamlit (login, input kode outlet, peta, simpan plan, download Excel).
- `db.py`: semua akses Supabase (`fetch_outlets`, `update_coords`, `fetch_district_refs`). Query Supabase hanya boleh ditulis di file ini.
- `optimizer.py`: logika murni tanpa Streamlit. Isinya pembagian outlet ke 12 slot hari (`cluster_days`), urutan kunjungan (`solve_tsp` dengan OR-Tools, fallback `nn_2opt`), jarak, dan ekspor Excel.
- `plan_b.py`: optimasi jarak ikut jalan memakai OpenRouteService.
- `roads.py`, `theme.py`: pendukung peta dan tema.

## Aturan
- Ubah hanya bagian yang perlu. Jangan menulis ulang file dari nol.
- Lihat dulu bagian kode yang akan diubah. Setelah mengubah, jalankan `pytest`.
- Logika perhitungan masuk ke `optimizer.py`, bukan `app.py`, supaya bisa dites tanpa Streamlit.
- Kunci dan password hanya lewat `st.secrets` (contoh di `.streamlit/secrets.toml.example`). Jangan menulis kunci di kode, dan jangan commit `.streamlit/secrets.toml`.
- Teks di tampilan memakai Bahasa Indonesia.
- Koordinat wajar dibatasi wilayah Surabaya Raya (`LAT_MIN..LON_MAX` di `optimizer.py`). Depot ada di konstanta `DEPOT`.
- Hari Sabtu kapasitasnya setengah kuota harian. Jangan ubah aturan ini tanpa diminta.

## Test
```
pip install -r requirements.txt pytest
pytest
```
GitHub Actions menjalankan test yang sama setiap ada push.

## Monitoring
`monitor.py` mengirim notif WhatsApp (CallMeBot) setiap ada error yang tidak tertangkap. Dipasang lewat `monitor.pasang(...)` di bagian atas `app.py`, dan nomor + apikey diambil dari secrets `[callmebot]`. Jangan hapus baris itu.
