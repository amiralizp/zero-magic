@echo off
setlocal
cd /d "%~dp0"
title Gantry database backup

echo [Gantry] Backing up the Gantry database...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\backup-db.ps1"
if errorlevel 1 (
  echo.
  echo [Gantry] Backup failed. See backups\backup.log
  pause
  exit /b 1
)

echo.
echo [Gantry] Done. The file is in the backups folder.
pause
