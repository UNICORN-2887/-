@echo off
chcp 65001 >nul
title DeadMaze 一键安装

echo.
echo ============================================
echo   DeadMaze 游戏自动化 - 环境安装
echo ============================================
echo.
echo   本脚本将自动完成以下步骤:
echo   [1] 检测 Python 环境
echo   [2] 安装 Python 依赖库
echo   [3] 检测 Tesseract OCR (可选)
echo   [4] 提示 OBS Studio 安装 (可选)
echo ============================================
echo.

:: ── 1. 检测 Python ──
echo [1/4] 检测 Python...
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo [错误] 未检测到 Python!
    echo.
    echo 请先安装 Python 3.10 或更高版本:
    echo   1. 打开 https://www.python.org/downloads/
    echo   2. 下载最新版 Python
    echo   3. ★ 安装时务必勾选 "Add Python to PATH"
    echo   4. 安装完成后重新运行本脚本
    echo.
    pause
    exit /b 1
)

python --version
echo [OK] Python 已就绪
echo.

:: ── 2. 安装依赖 ──
echo [2/4] 安装 Python 依赖库 (可能需要几分钟)...
echo.
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo.
    echo [警告] 部分依赖安装失败, 尝试逐个安装...
    pip install opencv-python numpy pywin32 easyocr pytesseract ultralytics flask mss pygrabber psutil
)
echo.
echo [OK] 依赖安装完成
echo.

:: ── 3. 检测 Tesseract ──
echo [3/4] 检测 Tesseract OCR...
where tesseract >nul 2>nul
if %errorlevel% neq 0 (
    echo [提示] Tesseract 未安装 (OCR识别可能受限)
    echo.
    echo 推荐安装 (提高中文字识别率):
    echo   1. 下载: https://github.com/UB-Mannheim/tesseract/wiki
    echo   2. 安装到 E:\Tools\tesseract  (或任意路径)
    echo   3. 安装时勾选中文语言包 Chinese Simplified
    echo.
    echo 如果不需要OCR功能可以跳过此步骤
) else (
    tesseract --version 2>nul | findstr /i "tesseract"
    echo [OK] Tesseract 已就绪
)
echo.

:: ── 4. 提示 OBS ──
echo [4/4] 提示 OBS Studio...
echo.
echo [重要] 请确认 OBS Studio 已安装并配置虚拟摄像头:
echo   1. 下载 OBS Studio: https://obsproject.com/
echo   2. 安装后打开 OBS → 工具 → 虚拟摄像头 → 启动
echo   3. 添加游戏窗口为采集源
echo   4. 确保虚拟摄像头输出分辨率为 1920x1080
echo.
echo ============================================
echo   安装完成!
echo ============================================
echo.
echo   接下来:
echo   1. 双击 "1配置.bat" → 设置游戏路径 + 标定ROI
echo   2. 双击 "2导航.bat" → 启动自动化
echo.
echo   详细教程: https://blog.219882.xyz/deadmaze/
echo.
pause
