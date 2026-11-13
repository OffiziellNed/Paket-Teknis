@echo off
setlocal
title Push ke GitHub
cd /d "%~dp0"

where git >nul 2>nul
if errorlevel 1 (
  echo [GAGAL] Git belum terpasang. Unduh dari https://git-scm.com/download/win
  echo Atau pakai GitHub Desktop - lihat DEPLOY_VERCEL.md.
  pause
  exit /b 1
)

echo PENTING: repo GitHub harus PRIVATE - folder paket\ berisi NPWP dan faktur asli.
echo Buat dulu repo kosong di https://github.com/new  - pilih Private, tanpa README.
echo.
set /p REPO=Tempel URL repo, contoh https://github.com/qoin/rekap-pph.git :
if "%REPO%"=="" exit /b 1

rem --- identitas git untuk commit ---
set "GEMAIL="
for /f "delims=" %%i in ('git config user.email 2^>nul') do set "GEMAIL=%%i"
if not defined GEMAIL call :askid

if not exist ".git" (
  git init -b main || goto :fail
  git add -A || goto :fail
  git commit -m "Rekap PPh Unifikasi - commit awal" || goto :fail
) else (
  rem commit awal yang disiapkan diganti ke identitas git Anda, hanya bila belum pernah di-push
  git rev-parse --abbrev-ref --symbolic-full-name @{u} >nul 2>nul
  if errorlevel 1 git commit --amend --reset-author --no-edit >nul 2>nul
  git add -A
  git commit -m "Update" >nul 2>nul
)

git remote remove origin >nul 2>nul
git remote add origin %REPO% || goto :fail
git push -u origin main || goto :fail

echo.
echo Selesai. Lanjutkan langkah Vercel di DEPLOY_VERCEL.md.
pause
exit /b 0

:askid
set /p GNAME=Nama Anda untuk commit git:
set /p GEMAIL=Email akun GitHub Anda:
git config --global user.name "%GNAME%"
git config --global user.email "%GEMAIL%"
goto :eof

:fail
echo.
echo [GAGAL] Lihat pesan error di atas.
pause
exit /b 1
