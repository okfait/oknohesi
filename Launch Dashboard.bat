@echo off
title okNoHesi Dashboard
cd /d "%~dp0"

:: Check if server is already running
curl -s http://127.0.0.1:5827/api/health >nul 2>&1
if %errorlevel% == 0 (
    echo Server already running, opening dashboard...
    start "" "http://127.0.0.1:5827"
    goto :end
)

echo Starting okNoHesi server...
:: Launch Python server silently (no console window)
start "" /min pythonw server.py

:: Wait briefly then open browser
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:5827"

echo Dashboard opened!
:end
exit
