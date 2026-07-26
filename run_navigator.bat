@echo off
chcp 65001 >nul
title DeadMaze 导航

echo.
echo ============================================
echo   DeadMaze 导航 ^& 战斗
echo ============================================
echo.
echo   启动前请确认:
echo   [*] OBS 虚拟摄像头已开启 (1920x1080)
echo   [*] DeadMaze 游戏已运行
echo   [*] 已通过 "run_config.bat" 完成标定
echo ============================================
echo.

:: ── 扫描 map/ 下的可用地图 ──
setlocal enabledelayedexpansion
set COUNT=0
echo   可用地图:
echo   ──────────────────────────────────────
for /d %%d in (map\*) do (
    set /a COUNT+=1
    set NAME=%%~nxd
    :: 检查是否有可达图
    set REACH=%%d\!NAME!_reachable.png
    set CAMP=%%d\!NAME!_campfire.json
    set STATUS=未标定
    if exist "!REACH!" set STATUS=已标定
    echo     [!COUNT!]  !NAME!  [!STATUS!]
)
echo   ──────────────────────────────────────
if %COUNT%==0 (
    echo   没有找到任何地图!
    echo   请先运行建图工具或下载地图
    pause
    exit /b 1
)

echo.
set /p CHOICE="请选择地图 [1-%COUNT%] (直接回车=1): "
if "%CHOICE%"=="" set CHOICE=1

:: ── 根据选择构建路径 ──
set IDX=0
for /d %%d in (map\*) do (
    set /a IDX+=1
    if !IDX!==%CHOICE% (
        set MAP_NAME=%%~nxd
        set MAP_JPG=%%d\!MAP_NAME!.jpg
        set MAP_PNG=%%d\!MAP_NAME!_reachable.png
    )
)

if not defined MAP_NAME (
    echo 无效选择!
    pause
    exit /b 1
)

echo.
echo   启动: %MAP_NAME%
echo   ──────────────────────────────────────
echo   操作提示:
echo   左键=起点 ^| 右键=终点 ^| Enter=开始导航
echo   空格=暂停 ^| Esc=停止 ^| Q=退出
echo   H=返航 ^| M=循环巡逻 ^| 1-4=技能
echo   ──────────────────────────────────────
echo.

:: ── 启动 ──
python navigator.py "%MAP_PNG%" --map "%MAP_JPG%"

pause
