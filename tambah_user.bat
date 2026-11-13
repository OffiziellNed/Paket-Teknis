@echo off
setlocal
title Tambah / ubah user
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Jalankan setup.bat dulu.
  pause
  exit /b 1
)
echo Role: 1 = Tax Support   2 = Manager FAT   3 = Admin
echo.
set /p EMAIL=Email (@qoin.id):
set /p R=Pilih role (1/2/3):
set "ROLE=TAX_SUPPORT"
if "%R%"=="2" set "ROLE=MANAGER_FAT"
if "%R%"=="3" set "ROLE=ADMIN"
set /p SIGNER=Nama penanda tangan yang ditautkan (kosongkan bila tidak ada, contoh Suryawati):
".venv\Scripts\python.exe" run.py add-user %EMAIL% %ROLE% %SIGNER%
pause
