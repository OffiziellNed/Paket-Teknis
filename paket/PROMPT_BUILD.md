# Prompt Build – Website Rekap PPh Unifikasi Qoin (QDI & QKI)

> Salin seluruh isi file ini ke AI coding assistant (Claude Code, Cursor, dll.) atau berikan ke developer sebagai brief. Baca juga dokumen requirement (`PRD_Requirement.md`, hasil unduhan dari dokumen requirement) dan semua file di folder `data/`, `samples/`, `schema/`, `scripts/` sebelum mulai.

## Peran & tujuan
Kamu adalah full-stack engineer. Bangun web app internal untuk tim Finance PT Qoin Digital Indonesia yang mereproduksi rekap PPh Unifikasi bulanan (PPh 23, PPh Final 4(2), ringkasan PPh 21) untuk dua entitas:
- **QDI** – PT Qoin Digital Indonesia, NPWP 0855609921034000
- **QKI** – PT Qoinpay Kripto Indonesia (d/h PT Loyalty Program Indonesia), NPWP 0028998276031000 (sama dengan LPI, sudah dikonfirmasi; simpan sebagai setting)

Dari input transaksi + upload faktur pajak per masa, aplikasi menghasilkan:
1. XML BPU Coretax per entitas (format persis `samples/BPU_Template.xml`; contoh benar `samples/BPU_QDI_Okt2026.xml`).
2. PDF laporan per entitas yang **meniru desain Excel lama** (acuan visual: `samples/Contoh_Cetak_Okt_2026.pdf`).
3. Data sheet Excel per entitas dengan struktur yang sama dengan sheet di `data/Workbook_Sumber_Rekapan_Pajak_QDI_QKI.xlsx` (sheet "PPH 23 QDI 2026" dan "PPh 23 LPI 2024 - 26").
Lalu mengirim semuanya via email ke **finance@qoin.id** dan **reconcile@qoin.id**.

## Fitur wajib (urut prioritas)
1. **Import data historis** dari workbook Excel / CSV di `data/` ke database (`schema/database.sql`). Total per masa harus sama persis dengan sheet.
2. **Master**: entitas, vendor (`data/master_vendor.csv`), KOP (`data/master_kop.csv`). KOP sewa tanah/bangunan = **28-403-02** (28-403-01 ditolak Coretax).
3. **Input transaksi per masa** (manual dan **upload massal** via `templates/Template_Bulk_Transaksi_PPh23.xlsx`/CSV dengan preview status per baris, mode Tambah/Ganti masa, dan file koreksi) dengan auto-fill dari vendor; section: PPh 23, PPh 23 Project QRIS, PPh Final 4(2), PPh 21 Freelance; total otomatis; input PPh 21 bulanan.
4. **Isi otomatis (PRD bagian 4.2)**: autocomplete vendor (ketik "rin" → Rintis) mengisi NPWP, NITKU, section, jenis jasa, KOP, tarif, notes; upload faktur membuat draft lengkap untuk SEMUA vendor di master (status Perlu konfirmasi, konfirmasi massal), menggabungkan dengan draft yang ada, panel Vendor baru, vendor `dipotong_pph23=Tidak` diabaikan, draft transaksi rutin saat buka masa.
5. **Saran nomor invoice**: tampilkan 5 invoice terakhir vendor + prediksi nomor berikutnya + validasi pola (hijau/kuning/merah). Detail di PRD bagian 6.
6. **Upload faktur massal** (banyak PDF sekaligus / satu atau beberapa ZIP, maks 300 faktur atau 200 MB), parsing (referensi: `scripts/parse_faktur.py`, hasil yang diharapkan: `samples/expected_parse_faktur_okt2026.json`), pencocokan ke transaksi (hasil yang diharapkan: `samples/expected_crosscheck_okt2026.csv`), dan **draft otomatis** (bisa ditandai *Tidak dipotong* per faktur dengan alasan) transaksi QRIS untuk Rintis (0015430614062000), ALTO (0016264426015000), PTEN (0840718738071000) dengan KOP 24-104-18, tarif 2%, DPP = harga jual.
7. **Generate output** XML (referensi: `scripts/generate_bpu_xml.py`), PDF, XLSX; preview; riwayat versi.
8. **Approval** Manager FAT, kunci masa, **kirim email** dengan 3 lampiran per entitas.
9. **Import export data pemotongan Coretax (PRD 7.4)** setelah Approve: baca `samples/coretax_export_bupot_sep2026.xlsx` (header by nama kolom), cocokkan per entitas (NITKU) + masa + NPWP + DPP (+KOP), preview status, isi No Bupot, regenerate PDF/XLSX. Referensi: `scripts/import_bupot_coretax.py` (harus 15/15 cocok dengan data September 2026).
10. Audit trail, SSO Microsoft 365 (Entra ID) domain @qoin.id, role Tax Support / Manager FAT / Admin.

## Aturan bisnis penting
- DPP PPh 23 = harga jual/penggantian sebelum PPN (bukan DPP nilai lain PPN).
- PPh = DPP × tarif; simpan desimal, dibulatkan ke rupiah terdekat (0,5 ke atas) seperti Coretax.
- NPWP 15 digit → 16 digit dengan menambah "0" di depan; NITKU = NPWP16 + "000000".
- `TaxCertificate` = `N/A`, `Document` = `CommercialInvoice`, `GovTreasurerOpt` = `N/A`, `<SP2DNumber />` kosong.
- Tanggal pemotongan wajib di dalam masa; invoice bulan sebelumnya → default akhir bulan masa.
- PPh 21 tidak masuk XML, hanya di laporan.
- Tagihan PT Mahesa Cipta: pilihan per transaksi Dikenakan PPh Final 10% (default) / Dibebaskan; BCA dan Telkom tidak dipotong PPh 23.
- PDF: kolom jenis jasa & no faktur tidak dicetak; semua sel bergaris penuh; baris kosong PPh 21 freelance disembunyikan; blok ttd default "Dibuat oleh" (Rizal Nur Furqon – Reconciliation Supervisor & Tax Support) dan "Diperiksa oleh" (Suryawati – Manager FAT).
- **Opsi tanda tangan (PRD 7.2.1)**: 1–4 blok, label bebas (Dibuat/Diperiksa/Disetujui/Mengetahui), pilih penanda tangan dari daftar, mode kosong / gambar ttd / gambar ttd + stempel, kota bisa diubah, tanggal ttd default **Hari ini** (WIB saat generate) atau **Pilih tanggal** via kalender (disimpan per masa dan dipakai lagi saat PDF dibuat ulang; peringatan bila sebelum akhir masa; format "Jakarta, 6 November 2026"), preset per entitas. Gambar ttd pemeriksa hanya tercetak setelah Approve (sebelumnya blok kosong + tanda DRAFT); setiap orang hanya bisa memakai ttd-nya sendiri; snapshot ttd dicatat di output_log.

## Definisi selesai
Semua checklist di PRD bagian 11 (Acceptance criteria) lulus menggunakan data Oktober 2026 di folder `samples/`. Target angka QDI Oktober 2026: PPh 23 Rp 2.373.193; PPh Final Rp 661.191; Total Pajak Rp 3.034.384 (11 bupot; faktur Rintis Annual Fee QRIS Rp 6.000.000 ditandai Tidak dipotong). QKI: 1 bupot, PPh 23 Rp 2.919.594.

## Cara kerja yang diminta
- Mulai dengan rencana singkat + struktur folder, lalu kerjakan per fitur sesuai urutan di atas, dengan test otomatis untuk parser faktur, generator XML, dan perhitungan total.
- Jangan mengubah aturan bisnis tanpa konfirmasi; catat asumsi di `ASSUMPTIONS.md`.
- Email dikirim lewat Microsoft Graph API (Microsoft 365). Kredensial (Graph, SSO) lewat environment variable, jangan di-commit.
