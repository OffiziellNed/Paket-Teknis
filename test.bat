@echo off
title Test otomatis Rekap PPh
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Jalankan setup.bat dulu.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pytest -q tests
pause
