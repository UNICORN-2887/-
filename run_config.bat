@echo off
cd /d "%~dp0"
title DeadMaze Config

echo.
echo ============================================
echo   DeadMaze - Config ^& Calibration
echo ============================================
echo.
echo   Starting web server...
echo   (Takes ~6 seconds, please wait...)
echo ============================================
echo.

start "DeadMaze_Server" python config_server.py

:: Poll until server responds
echo   Waiting for server to be ready...
:loop
timeout /t 2 /nobreak >nul
powershell -Command "try{$r=Invoke-WebRequest -Uri 'http://127.0.0.1:5050' -TimeoutSec 2;exit 0}catch{exit 1}" >nul 2>nul
if %errorlevel% neq 0 goto loop

echo   Server ready! Opening browser...
start "" http://127.0.0.1:5050
echo   Calibration page: http://127.0.0.1:5050/calibrate
echo.
echo   Close this window to stop the server.
pause >nul
