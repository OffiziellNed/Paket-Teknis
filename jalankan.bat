@echo off
setlocal
title Rekap PPh Unifikasi - server
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Belum di-setup. Menjalankan setup.bat dulu ...
  call setup.bat || exit /b 1
)
if not exist "instance\rekap.db" (
  echo Database belum ada. Menjalankan setup.bat dulu ...
  call setup.bat || exit /b 1
)

if "%PORT%"=="" set "PORT=5000"
echo ================================================
echo   Rekap PPh Unifikasi berjalan di:
echo   http://localhost:%PORT%
echo   Tutup jendela ini (atau tekan Ctrl+C) untuk berhenti.
echo ================================================

rem buka browser setelah 3 detik
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:%PORT%"

".venv\Scripts\python.exe" run.py
echo.
echo Server berhenti.
pause
