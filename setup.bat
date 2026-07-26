@echo off
cd /d "%~dp0"
title DeadMaze Setup

echo.
echo ============================================
echo   DeadMaze - Environment Setup
echo ============================================
echo.
echo   Steps:
echo   [1] Check Python
echo   [2] Install dependencies
echo   [3] Check Tesseract OCR (optional)
echo   [4] OBS Studio reminder (optional)
echo ============================================
echo.

:: [1] Python
echo [1/4] Checking Python...
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Python not found!
    echo.
    echo Please install Python 3.10+ from:
    echo   https://www.python.org/downloads/
    echo   ** Check "Add Python to PATH" during install **
    echo.
    pause
    exit /b 1
)
python --version
echo [OK] Python ready
echo.

:: [2] Dependencies
echo [2/4] Installing Python packages (may take a few minutes)...
echo.
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo.
    echo [WARN] Some packages failed, retrying individually...
    pip install opencv-python-headless opencv-python numpy pywin32 easyocr pytesseract ultralytics flask mss pygrabber psutil
) else (
    :: 确保GUI版opencv后装覆盖headless (easyocr等依赖headless但需要GUI)
    pip install opencv-python -q 2>nul
)
echo.
echo [OK] Dependencies installed
echo.

:: [3] Tesseract
echo [3/4] Checking Tesseract OCR...
where tesseract >nul 2>nul
if %errorlevel% neq 0 (
    echo [INFO] Tesseract not found (OCR may be limited)
    echo.
    echo Recommended for Chinese character recognition:
    echo   1. Download: https://github.com/UB-Mannheim/tesseract/wiki
    echo   2. Install to: E:\Tools\tesseract
    echo   3. Select Chinese Simplified language pack during install
    echo.
    echo Skip this step if you don't need OCR.
) else (
    tesseract --version 2>nul | findstr /i "tesseract"
    echo [OK] Tesseract ready
)
echo.

:: [4] OBS
echo [4/4] OBS Studio reminder...
echo.
echo [IMPORTANT] Make sure OBS Studio is configured:
echo   1. Download: https://obsproject.com/
echo   2. Tools ^> Virtual Camera ^> Start
echo   3. Add game window as capture source
echo   4. Set output resolution to 1920x1080
echo.
echo ============================================
echo   Setup complete!
echo ============================================
echo.
echo   Next steps:
echo   1. Double-click run_config.bat to calibrate
echo   2. Double-click run_navigator.bat to start
echo.
echo   Guide: https://blog.219882.xyz/deadmaze/
echo.
pause
