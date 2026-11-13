@echo off
setlocal
title Setup Rekap PPh Unifikasi
cd /d "%~dp0"

echo ================================================
echo   SETUP - Rekap PPh Unifikasi (QDI ^& QKI)
echo ================================================
echo.

rem --- cari Python (py launcher atau python) ---
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [GAGAL] Python belum terpasang.
  echo Unduh Python 3.11+ dari https://www.python.org/downloads/
  echo dan centang "Add python.exe to PATH" saat instalasi.
  pause
  exit /b 1
)
%PY% --version

rem --- virtual environment ---
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo [1/4] Membuat virtual environment .venv ...
  %PY% -m venv .venv || goto :error
) else (
  echo [1/4] Virtual environment sudah ada.
)
set "VPY=%~dp0.venv\Scripts\python.exe"

echo.
echo [2/4] Memasang library (butuh internet, beberapa menit) ...
"%VPY%" -m pip install --upgrade pip >nul
"%VPY%" -m pip install -r requirements-dev.txt || goto :error

echo.
if not exist ".env" (
  echo [3/4] Membuat file .env dari .env.example ...
  copy /y ".env.example" ".env" >nul
) else (
  echo [3/4] File .env sudah ada - tidak diubah.
)

echo.
if not exist "instance\rekap.db" (
  echo [4/4] Import master dan data historis ke database ...
  "%VPY%" run.py seed || goto :error
  echo.
  set /p ADMIN_EMAIL=Email admin pertama, contoh rizal@qoin.id: 
  call :adduser
) else (
  echo [4/4] Database sudah ada - lewati import.
)

echo.
echo ================================================
echo   Setup selesai. Jalankan "jalankan.bat".
echo ================================================
pause
exit /b 0

:adduser
if "%ADMIN_EMAIL%"=="" goto :eof
"%VPY%" run.py add-user %ADMIN_EMAIL% ADMIN
echo Untuk user lain / menautkan penanda tangan: jalankan tambah_user.bat
goto :eof

:error
echo.
echo [GAGAL] Setup berhenti karena error di atas.
pause
exit /b 1
