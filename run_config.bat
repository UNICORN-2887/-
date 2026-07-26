@echo off
cd /d "%~dp0"
title DeadMaze Config

echo.
echo ============================================
echo   DeadMaze - Config ^& Calibration
echo ============================================
echo.
echo   Starting web config panel...
echo.
echo   Browser will open: http://127.0.0.1:5050
echo   Press Ctrl+C to exit
echo   Calibration page: http://127.0.0.1:5050/calibrate
echo ============================================
echo.

start "" http://127.0.0.1:5050

python config_server.py

pause
