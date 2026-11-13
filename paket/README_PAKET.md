# Paket Teknis – Website Rekap PPh Unifikasi Qoin (QDI & QKI)

Disiapkan oleh Rizal Nur Furqon (Reconciliation Supervisor & Tax Support), 6 November 2026.

| File / folder | Isi |
|---|---|
| Dokumen requirement | [Requirement Website Rekap PPh Unifikasi](https://claude.ai/artifact/4LhWpioGDoYHTFJXS7xf3E) — unduh sebagai Word/PDF/Markdown dari dokumen tersebut dan simpan sebagai `PRD_Requirement.md` di folder ini |
| `PROMPT_BUILD.md` | Prompt/brief siap pakai untuk developer atau AI coding assistant |
| `data/entitas.csv` | Data QDI & QKI (NPWP, NITKU, judul laporan) |
| `data/master_kop.csv` | Kode Objek Pajak Coretax yang dipakai + status verifikasi |
| `data/master_vendor.csv` | Vendor dari riwayat: NPWP16, NITKU, jenis jasa, KOP default, 3 invoice terakhir |
| `data/transaksi_QDI_2026.csv` | Transaksi QDI Jan–Okt 2026 (seed / data uji) |
| `data/transaksi_QKI_2024_2026.csv` | Transaksi QKI/LPI 2024–2026 |
| `data/Workbook_Sumber_Rekapan_Pajak_QDI_QKI.xlsx` | Workbook Excel asli (2023–2026) + sheet cetak contoh |
| `samples/BPU_Template.xml` | Template XML resmi Coretax |
| `samples/BPU_QDI_Okt2026.xml`, `BPU_QKI_Okt2026.xml` | Contoh XML yang benar (QDI sudah lolos validasi Coretax setelah KOP sewa = 28-403-02) |
| `samples/Contoh_Cetak_Okt_2026.pdf` | Acuan visual PDF laporan QDI & QKI |
| `samples/faktur_okt2026/` | 20 faktur pajak masukan Oktober 2026 (data uji parser) |
| `samples/expected_parse_faktur_okt2026.json` | Hasil parsing yang diharapkan |
| `samples/expected_crosscheck_okt2026.csv` | Hasil pencocokan invoice ↔ faktur yang diharapkan |
| `templates/Template_Bulk_Transaksi_PPh23.xlsx` | Template upload massal transaksi + PPh 21 bulanan (requirement bagian 4.1) |
| `samples/coretax_export_bupot_sep2026.xlsx` | Contoh export data pemotongan Coretax (15 bupot September 2026) untuk uji import No Bupot |
| `scripts/import_bupot_coretax.py` | Referensi pencocokan export Coretax ke transaksi |
| `schema/database.sql` | Skema database referensi (PostgreSQL) |
| `scripts/parse_faktur.py` | Parser faktur referensi (Python + pdftotext) |
| `scripts/generate_bpu_xml.py` | Generator XML BPU referensi |

**Kerahasiaan:** paket ini berisi NPWP dan data pajak perusahaan. Hanya untuk tim internal; jangan di-upload ke repo publik.

**Keputusan yang sudah dikonfirmasi (6-Nov-2026):** NPWP QKI tetap 0028998276031000; tagihan Mahesa Cipta ada yang dikenakan PPh Final 4(2) dan ada yang dibebaskan (dipilih per tagihan); BCA dan Telkom tidak dipotong PPh 23; email dan SSO memakai Microsoft 365.

**Revisi 6-Nov-2026:** Rintis Annual Fee QRIS Rp 6.000.000 (AR#261003897) tidak dipotong PPh 23; semua data uji dan contoh output sudah disesuaikan.
