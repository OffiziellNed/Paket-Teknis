# Rekap PPh Unifikasi Qoin (QDI & QKI) – Web App Python

Web app internal (Flask + SQLAlchemy) yang mereproduksi rekap PPh Unifikasi bulanan sesuai `paket/PROMPT_BUILD.md`:
input transaksi, upload faktur, crosscheck, XML BPU Coretax, PDF laporan gaya Excel lama, data sheet XLSX,
approval Manager FAT, email via Microsoft 365, dan import No Bupot dari export Coretax.

> **Repo ini WAJIB private.** Folder `paket/` berisi NPWP, transaksi, dan faktur pajak asli (dipakai untuk import
> data awal dan test otomatis).

Isi repo:

| Path | Isi |
|---|---|
| `app/` | Aplikasi Flask (lihat bagian Struktur) |
| `api/index.py`, `vercel.json` | Entry point & konfigurasi Vercel |
| `paket/` | Paket Teknis: `data/` (CSV master + transaksi historis), `samples/`, `templates/`, `schema/`, `scripts/`, `PROMPT_BUILD.md` |
| `tests/` | 14 test otomatis (SQLite; Postgres via `TEST_DATABASE_URL`) |
| `*.bat` | Setup & jalankan di Windows |

## Deploy ke Vercel

Detail langkah ada di [`DEPLOY_VERCEL.md`](DEPLOY_VERCEL.md). Ringkasnya:

1. Push repo ini ke GitHub (**private**) – lihat `push_ke_github.bat` atau GitHub Desktop.
2. Vercel → **Add New → Project** → import repo → Framework Preset **Other** → Deploy.
3. Vercel → project → **Storage** → buat database **Neon (Postgres)** dan hubungkan ke project
   (otomatis mengisi `DATABASE_URL`).
4. Isi Environment Variables (`SECRET_KEY`, `ENTRA_*`, `ADMIN_EMAILS`, email Graph) → **Redeploy**.
5. Login dengan Microsoft 365 → Dashboard → **Import data awal**.

Penyesuaian khusus Vercel yang sudah ada di kode: file (faktur, output, ttd) disimpan di database, upload faktur
dipecah per batch ≤ 3 MB oleh browser (ZIP dibuka di browser), koneksi DB tanpa pool, HTTPS di belakang proxy,
parser memakai pdfplumber (pdftotext tidak ada di Vercel), dan login development otomatis mati.

## Menjalankan di komputer sendiri (Windows, file .bat)

1. Pasang Python 3.11+ dari python.org (centang **Add python.exe to PATH**).
2. Dobel-klik **setup.bat** – membuat `.venv`, memasang library, membuat `.env`, import data, dan membuat user admin.
3. Dobel-klik **jalankan.bat** – server jalan dan browser terbuka di http://localhost:5000.

| File | Fungsi |
|---|---|
| `setup.bat` | Setup pertama kali (aman dijalankan ulang) |
| `jalankan.bat` | Menjalankan aplikasi (otomatis setup bila belum) |
| `tambah_user.bat` | Tambah/ubah user + role, sekaligus tautkan ke penanda tangan (mis. Suryawati) |
| `test.bat` | Menjalankan 14 test otomatis |
| `backup_db.bat` | Salin database ke folder `backup\` dengan cap waktu |

## Cara menjalankan manual (Windows / Linux)

```bash
cd rekap-pph
python -m venv .venv
.venv\Scripts\activate            # Linux/Mac: source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env             # Linux: cp .env.example .env  -> isi nilainya
python run.py seed                 # import master + transaksi historis (QDI 2026, QKI 2024–2026)
python run.py add-user rizal@qoin.id ADMIN Rizal Nur Furqon
python run.py add-user suryawati@qoin.id MANAGER_FAT Suryawati
python run.py                      # http://localhost:5000
python -m pytest -q tests          # 14 test otomatis (TEST_DATABASE_URL=... untuk uji di Postgres)
```

`python run.py add-user <email> <ROLE> [nama penanda tangan]` juga menautkan akun ke data penanda tangan
(supaya orang itu bisa meng-upload dan memakai gambar ttd-nya sendiri).

Untuk production: `pip install waitress` (Windows) – `run.py` otomatis memakainya – atau
`gunicorn "run:app"` (Linux) di belakang HTTPS. Set `DEV_LOGIN=0`.

## Struktur

```
app/
  core/                 logika murni, tanpa Flask – inilah yang dites
    rules.py            NPWP16/NITKU, pembulatan Coretax (0,5 ke atas), tanggal pemotongan, section
    faktur_parser.py    parser faktur (pdftotext bila ada, fallback pdfplumber), ZIP, batas 300 faktur/200 MB
    matching.py         crosscheck invoice↔faktur, draft otomatis dari faktur, import No Bupot Coretax
    invoice_suggest.py  prediksi nomor invoice berikutnya + validasi pola hijau/kuning/merah
    bulk.py             upload massal (template xlsx / csv), preview per baris, file koreksi
    report.py           model laporan (urutan, nomor, subtotal, total) dipakai PDF & XLSX
    report_pdf.py       PDF meniru Contoh_Cetak_Okt_2026.pdf
    report_xlsx.py      data sheet dengan kolom sheet 'PPH 23 QDI 2026' / 'PPh 23 LPI 2024 - 26'
    xml_bpu.py          XML BPU persis BPU_Template.xml + validasi
    historical.py, masters.py   pembaca CSV di data/
  models.py             tabel (mengikuti schema/database.sql) + audit trail otomatis
  storage.py            simpan file (faktur, output, ttd, stempel) di database
  services.py           penghubung DB ↔ core (masa, output & versi, email, faktur, bupot)
  views.py, auth.py     halaman, API autocomplete, SSO Entra ID & role
  mailer.py             Microsoft Graph sendMail (atau .eml tersimpan saat MAIL_DRY_RUN=1)
  static/jszip.min.js   membuka ZIP faktur di browser (upload bertahap)
  templates/, static/
tests/                  test_core.py (parser, XML, total, crosscheck, bupot) + test_web.py (alur end-to-end)
```

## Alur kerja per masa

1. **Dashboard → Buka masa**: draft transaksi rutin (vendor `tagihan_rutin=Ya`) otomatis dibuat dengan prediksi nomor invoice.
2. **+ Transaksi**: ketik "rin" → Rintis; NPWP, section, jenis jasa, KOP, tarif terisi; panel 5 invoice terakhir,
   prediksi nomor berikutnya, dan indikator pola. Mahesa Cipta: pilih *Dikenakan PPh Final 10%* / *Dibebaskan*.
   Atau **Upload Massal** (template xlsx/csv) dengan preview, mode Tambah/Ganti masa, dan file koreksi.
3. **Faktur & crosscheck**: upload banyak PDF/ZIP → parsing → tabel pencocokan. Draft dibuat untuk semua vendor di
   master (status *Perlu konfirmasi*), digabung ke draft yang sudah ada; Rintis/ALTO/PTEN otomatis KOP 24-104-18, 2%,
   DPP = harga jual; vendor `dipotong_pph23=Tidak` diabaikan; panel *Vendor baru*; tombol *Tidak dipotong* per faktur.
4. Konfirmasi draft (massal), isi PPh 21 bulanan, atur **Tanda tangan** (1–4 blok, preset, kota, tanggal Hari ini/Pilih).
5. **Preview / Generate** XML + PDF + XLSX (tersimpan sebagai versi, dengan sha256 dan snapshot ttd).
6. **Ajukan** → Manager FAT **Approve** (masa terkunci, output final dibuat) → **Kirim email** ke finance@qoin.id &
   reconcile@qoin.id dengan 3 lampiran per entitas.
7. Setelah bupot terbit di Coretax: **Import No Bupot** dari export data pemotongan → No Bupot terisi, PDF/XLSX dibuat ulang.

## Konfigurasi SSO & email (Microsoft 365)

1. Entra ID → App registrations → New: redirect URI (Web) `https://<host>/auth/callback`.
2. Buat client secret. Isi `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET` di `.env`.
3. Untuk email: tambah *Application permission* Microsoft Graph `Mail.Send` + admin consent; isi `MAIL_SENDER`
   (mailbox pengirim) dan set `MAIL_DRY_RUN=0`. Disarankan batasi dengan Application Access Policy ke mailbox itu.
4. Login hanya untuk domain `ALLOWED_DOMAIN` (default qoin.id). User pertama / `ADMIN_EMAILS` menjadi Admin;
   user lain otomatis Tax Support, role diubah Admin di menu **User**.

## Hasil verifikasi (data Oktober 2026)

- XML QDI & QKI yang dihasilkan **identik byte-per-byte** dengan `samples/BPU_QDI_Okt2026.xml` dan `BPU_QKI_Okt2026.xml`.
- QDI: PPh 23 Rp 2.373.193; PPh Final Rp 661.191; Total Pajak Rp 3.034.384; 11 bupot. QKI: 1 bupot, Rp 2.919.594 (No 9).
- Parser: 20/20 faktur sama dengan `expected_parse_faktur_okt2026.json` (pdftotext maupun pdfplumber).
- Crosscheck sama dengan `expected_crosscheck_okt2026.csv` (status per faktur/invoice).
- Import No Bupot September 2026: 15/15 cocok.

**Kerahasiaan:** repo (folder `paket/`), database, dan folder `instance/` berisi NPWP & data pajak. Repo GitHub harus private.
