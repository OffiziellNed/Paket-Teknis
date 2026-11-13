# Deploy ke Vercel – langkah demi langkah

Perkiraan waktu: 20–30 menit. Yang dibutuhkan: akun GitHub, akun Vercel, dan akses admin Microsoft Entra ID
(atau minta tim IT) untuk SSO dan email.

> Vercel plan **Hobby** hanya untuk pemakaian non-komersial. Untuk aplikasi internal perusahaan, gunakan plan **Pro**.

## 1. Push ke GitHub (repo PRIVATE)

**Cara A – GitHub Desktop (paling mudah)**
1. Buat repo baru di https://github.com/new → nama `rekap-pph` → pilih **Private** → jangan centang README → Create.
2. GitHub Desktop → File → **Add local repository** → pilih folder `rekap-pph` (sudah berisi commit awal).
3. Klik **Publish repository** → pastikan **Keep this code private** tercentang → Publish.

**Cara B – push_ke_github.bat**
1. Pasang Git for Windows (https://git-scm.com/download/win).
2. Buat repo kosong **Private** di https://github.com/new (tanpa README).
3. Dobel-klik `push_ke_github.bat`, tempel URL repo (mis. `https://github.com/qoin/rekap-pph.git`).
   Login GitHub akan muncul di browser saat pertama kali push.

## 2. Buat project di Vercel

1. https://vercel.com/new → **Import Git Repository** → pilih `rekap-pph`.
2. Framework Preset: **Other**. Root Directory: `./`. Build/Output settings: biarkan default.
3. Klik **Deploy**. Deploy pertama akan jalan, tapi masih memakai database sementara (ada banner merah) – lanjut ke langkah 3.

## 3. Database Postgres (Neon)

1. Vercel → project → tab **Storage** → **Create Database** → pilih **Neon (Serverless Postgres)** → region
   **Singapore (ap-southeast-1)** agar dekat Jakarta → Create.
2. **Connect** ke project `rekap-pph` untuk semua environment. Vercel otomatis menambahkan env `DATABASE_URL`.
3. Tabel dibuat otomatis saat aplikasi pertama kali jalan.

Semua file (faktur, XML/PDF/XLSX, gambar tanda tangan) disimpan di database ini – tidak perlu Blob/S3.

## 4. SSO Microsoft 365 (Entra ID)

1. https://entra.microsoft.com → **App registrations** → **New registration**
   - Name: `Rekap PPh Unifikasi`
   - Supported account types: *Accounts in this organizational directory only*
   - Redirect URI (Web): `https://<nama-project>.vercel.app/auth/callback`
     (tambahkan juga domain custom bila ada, dan `http://localhost:5000/auth/callback` untuk lokal)
2. Catat **Application (client) ID** dan **Directory (tenant) ID**.
3. **Certificates & secrets** → New client secret → catat **Value**.
4. Untuk email: **API permissions** → Add → Microsoft Graph → **Application permissions** → `Mail.Send` →
   **Grant admin consent**. (Disarankan IT membatasi dengan Application Access Policy ke mailbox pengirim saja.)

## 5. Environment Variables di Vercel

Project → **Settings → Environment Variables** (Production):

| Nama | Nilai |
|---|---|
| `SECRET_KEY` | string acak panjang (mis. hasil `python -c "import secrets;print(secrets.token_hex(32))"`) |
| `ENTRA_TENANT_ID` | Directory (tenant) ID |
| `ENTRA_CLIENT_ID` | Application (client) ID |
| `ENTRA_CLIENT_SECRET` | client secret Value |
| `ALLOWED_DOMAIN` | `qoin.id` |
| `ADMIN_EMAILS` | email admin, mis. `rizal@qoin.id` |
| `MAIL_SENDER` | mailbox pengirim, mis. `tax@qoin.id` |
| `MAIL_DRY_RUN` | `1` dulu untuk uji (email disimpan sebagai .eml), lalu `0` untuk kirim sungguhan |
| `DATABASE_URL` | otomatis dari Neon (langkah 3) |

Setelah mengisi → tab **Deployments** → deployment terakhir → **Redeploy**.

`DEV_LOGIN` selalu nonaktif di Vercel (URL-nya publik), jadi SSO wajib dikonfigurasi.

## 6. Pakai pertama kali

1. Buka `https://<nama-project>.vercel.app` → **Masuk dengan Microsoft 365** (pakai email di `ADMIN_EMAILS`).
2. Dashboard → **Import data awal** (master entitas, KOP, vendor, penanda tangan, transaksi QDI 2026 & QKI 2024–2026).
3. Menu **User**: tambahkan `suryawati@qoin.id` sebagai Manager FAT (user lain otomatis Tax Support saat login).
4. Menu **Penanda Tangan**: isi email Rizal & Suryawati agar masing-masing bisa meng-upload gambar ttd di **Profil**.

## Batasan Vercel yang perlu diketahui

- **Upload**: maks ±4,5 MB per request. Halaman Faktur sudah memecah upload otomatis (ZIP dibuka di browser, PDF
  dikirim per batch ≤ 3 MB). Upload Massal (.xlsx/.csv), export Coretax, dan gambar ttd biasanya jauh di bawah batas.
- **Waktu proses**: maks 60 detik per request (`vercel.json`). Proses normal (≤ 300 faktur per upload) jauh di bawahnya.
- **Cold start**: request pertama setelah lama tidak dipakai bisa butuh beberapa detik.

## Update aplikasi

Setiap `git push` ke branch `main` otomatis di-deploy ulang oleh Vercel. Push ke branch lain menghasilkan
*Preview Deployment* (memakai database yang sama bila env Preview diarahkan ke Neon yang sama – sebaiknya buat
branch database terpisah di Neon untuk preview).
