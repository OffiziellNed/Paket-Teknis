@echo off
title Backup database Rekap PPh
cd /d "%~dp0"
if not exist "instance\rekap.db" (
  echo Database belum ada.
  pause
  exit /b 1
)
if not exist "backup" mkdir backup
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "TS=%%i"
copy /y "instance\rekap.db" "backup\rekap-%TS%.db" >nul
echo Backup tersimpan: backup\rekap-%TS%.db
echo (Folder instance\storage berisi faktur dan output - salin juga bila perlu.)
pause
