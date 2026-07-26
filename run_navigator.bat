@echo off
chcp 65001 >nul 2>nul
title DeadMaze Navigator

echo.
echo ============================================
echo   DeadMaze - Navigation ^& Combat
echo ============================================
echo.
echo   Before starting:
echo   [*] OBS Virtual Camera ON (1920x1080)
echo   [*] DeadMaze game running
echo   [*] ROI calibrated (run_config.bat)
echo ============================================
echo.

:: Scan map/ directory
setlocal enabledelayedexpansion
set COUNT=0
echo   Available maps:
echo   ----------------------------------------
for /d %%d in (map\*) do (
    set /a COUNT+=1
    set NAME=%%~nxd
    set REACH=%%d\!NAME!_reachable.png
    set STATUS=unmarked
    if exist "!REACH!" set STATUS=READY
    echo     [!COUNT!]  !NAME!  [!STATUS!]
)
echo   ----------------------------------------
if %COUNT%==0 (
    echo   No maps found!
    echo   Please run map_stitcher or download a map first.
    pause
    exit /b 1
)

echo.
set /p CHOICE="Select map [1-%COUNT%] (Enter=1): "
if "%CHOICE%"=="" set CHOICE=1

:: Build paths from choice
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
    echo Invalid choice!
    pause
    exit /b 1
)

echo.
echo   Launching: %MAP_NAME%
echo   ----------------------------------------
echo   L-click=Start | R-click=Goal | Enter=Go
echo   Space=Pause | Esc=Stop | Q=Quit
echo   H=Campfire | M=Patrol | 1-4=Skills
echo   ----------------------------------------
echo.

python navigator.py "%MAP_PNG%" --map "%MAP_JPG%"

pause
