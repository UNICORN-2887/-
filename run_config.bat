@echo off
cd /d "%~dp0"
title DeadMaze Config

echo.
echo ============================================
echo   DeadMaze - Config ^& Calibration
echo ============================================
echo.
echo   Server starting (please wait ~6s)...
echo   Browser will open automatically.
echo ============================================
echo.

:: Start server in background, wait for it, then open browser
start /B python config_server.py
timeout /t 6 /nobreak >nul
start "" http://127.0.0.1:5050
timeout /t 1 /nobreak >nul
start "" http://127.0.0.1:5050/calibrate
echo   Config: http://127.0.0.1:5050
echo   Calibration: http://127.0.0.1:5050/calibrate
echo   Press Ctrl+C to stop server.
pause >nul
