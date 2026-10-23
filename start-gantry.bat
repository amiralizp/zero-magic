@echo off
setlocal
cd /d "%~dp0"
title Gantry

if not exist ".venv\Scripts\python.exe" (
  echo [Gantry] .venv was not found in this folder.
  echo [Gantry] Create it once with:
  echo     python -m venv .venv
  echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if errorlevel 1 (
  echo [Gantry] Port 8010 is already in use.
  echo [Gantry] Opening the console that is already running...
  start "" "http://127.0.0.1:8010/console"
  timeout /t 3 /nobreak >nul
  exit /b 0
)

echo [Gantry] Starting at http://127.0.0.1:8010/console
echo [Gantry] Keep this window open. Press Ctrl+C to stop the server.
echo.

if /I "%~1"=="--no-browser" goto run
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8010/console'"

:run
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8010
echo.
echo [Gantry] Server stopped.
pause
