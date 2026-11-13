# Asumsi & keputusan implementasi

Dokumen requirement (PRD) di link artifact tidak bisa dibuka saat pembuatan, jadi implementasi mengikuti
`PROMPT_BUILD.md`, `README.md`, data di `data/` dan contoh di `samples/`. Hal-hal berikut perlu dikonfirmasi tim:

1. **Total per section** = jumlah PPh per baris yang sudah dibulatkan (seperti nilai bupot Coretax). Untuk Okt 2026
   hasilnya sama dengan Excel (yang menjumlah nilai desimal lalu membulatkan tampilan).
2. **Crosscheck "Faktur tanpa transaksi"**: faktur yang hanya punya draft otomatis (belum dikonfirmasi) untuk vendor
   non-QRIS tetap berstatus *Faktur tanpa transaksi* dengan catatan "Draft dibuat dari faktur". Status
   *Cocok (draft otomatis QRIS)* khusus Rintis, ALTO, PTEN (flag `auto_qris_draft` di aturan vendor). LMI tetap
   draft biasa meskipun grupnya QRIS.
3. **Draft dan output**: transaksi *Perlu konfirmasi* dan tagihan Mahesa *Dibebaskan* tidak ikut XML/PDF/XLSX/total.
   Pengajuan approval ditolak selama masih ada draft.
4. **Nomor invoice di XML**: bagian sebelum tanda `|` (contoh PTEN), sesuai sampel XML yang lolos Coretax.
   Di PDF/XLSX nomor ditampilkan lengkap.
5. **Penomoran laporan**: QDI mulai 1 setiap masa; QKI berlanjut sejak 2025 (setting entitas
   `numbering_since_year`), sehingga INV/204/CLOUD-QKI/IX/2026 bernomor 9 seperti contoh cetak.
6. **Data historis**: diimpor dari `transaksi_QDI_2026.csv` dan `transaksi_QKI_2024_2026.csv`. Tahun masa QKI tidak
   ada di CSV, jadi ditentukan berurutan (tahun tidak mundur dan masa tidak sebelum bulan invoice). Sel bupot QKI
   yang berisi hasil rumus (mis. `3940721.95`) diabaikan. Masa selain Oktober 2026 diberi status APPROVED.
   Sheet QDI 2023–2025 di workbook belum diimpor (strukturnya berbeda-beda) – bisa lewat Upload Massal.
7. **Tarif QKI historis** diturunkan dari PPh/DPP (2% atau 10% → PPh Final 4(2)).
8. **KOP vendor kosong di master** diisi dari kolom `dipakai_untuk` di master KOP (Venturo → 24-104-24,
   SPI → 24-104-60). Vendor tanpa KOP (LPPI, LMI, Yohanes Aples, KAP Anwar) harus diisi KOP saat konfirmasi draft.
9. **Tanda tangan**: gambar ttd blok non-approval tercetak hanya bila mode gambar diatur oleh pemilik ttd sendiri;
   blok "perlu approval" tercetak hanya setelah orang itu sendiri meng-approve masa. Sebelum Approve, PDF diberi
   watermark DRAFT. Snapshot konfigurasi ttd disimpan di `output_log.signature_snapshot`.
10. **Status masa**: DRAFT → SUBMITTED → APPROVED (terkunci). Admin bisa membuka kunci (tercatat di audit).
    Import No Bupot tetap boleh pada masa terkunci (hanya kolom bupot yang berubah).
11. **Upload massal mode Ganti** menghapus semua transaksi masa terkait (yang belum terkunci) lalu mengisi ulang.
    Mode Tambah memperbarui transaksi bila NPWP + No Invoice sudah ada.
12. **Email**: satu email untuk semua masa terpilih (mis. QDI + QKI Oktober), 3 lampiran per entitas, penerima dari
    setting entitas (default finance@qoin.id, reconcile@qoin.id). `MAIL_DRY_RUN=1` menyimpan .eml di storage/outbox.
13. **Prediksi nomor invoice** bersifat saran: grup angka yang naik dinaikkan 1, bulan romawi/angka bulan dan tahun di
    akhir nomor disesuaikan masa. Validasi: merah = duplikat / pola beda; kuning = pola mirip atau nomor urut tidak
    naik (contoh 15/KTI/X/2026 setelah 29/KTI/IX/2026); hijau = sesuai pola.
14. **Vercel**: file disimpan di tabel `stored_file` (Postgres), bukan di disk/Blob, agar tetap privat dan permanen.
    Upload faktur dipecah per batch ≤ 3 MB dari browser karena batas body request Vercel 4,5 MB.
    `DEV_LOGIN` dipaksa nonaktif di Vercel.
