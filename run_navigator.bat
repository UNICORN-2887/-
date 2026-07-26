@echo off
cd /d "%~dp0"
title DeadMaze Navigator
setlocal enabledelayedexpansion

echo.
echo ============================================
echo   DeadMaze - Navigation
echo ============================================
echo.

:: Collect map names into arrays
set COUNT=0
for /d %%d in (map\*) do (
    set /a COUNT+=1
    set MAPDIR!COUNT!=%%d
    set MAPNAME!COUNT!=%%~nxd
)

if %COUNT%==0 (
    echo   No maps found in map\ directory!
    echo   Please run map_stitcher or download a map.
    pause
    exit /b 1
)

echo   Available maps:
echo   ----------------------------------------
for /l %%i in (1,1,%COUNT%) do (
    set STATUS=unmarked
    if exist "!MAPDIR%%i!\!MAPNAME%%i!_reachable.png" set STATUS=READY
    echo     [%%i]  !MAPNAME%%i!  [!STATUS!]
)
echo   ----------------------------------------

echo.
set /p CHOICE="Select map [1-%COUNT%] (Enter=1): "
if "%CHOICE%"=="" set CHOICE=1
if %CHOICE% gtr %COUNT% (
    echo Invalid: must be 1-%COUNT%
    pause
    exit /b 1
)
if %CHOICE% lss 1 (
    echo Invalid: must be 1-%COUNT%
    pause
    exit /b 1
)

set MAP_JPG=!MAPDIR%CHOICE%!\!MAPNAME%CHOICE%!.jpg
set MAP_PNG=!MAPDIR%CHOICE%!\!MAPNAME%CHOICE%!_reachable.png

echo.
echo   Map:  !MAPNAME%CHOICE%!
echo   JPG:  !MAP_JPG!
echo   PNG:  !MAP_PNG!
echo   ----------------------------------------
echo   L-click=Start | R-click=Goal | Enter=Go
echo   Space=Pause | Esc=Stop | Q=Quit
echo   H=Campfire | M=Patrol | 1-4=Skills
echo   ----------------------------------------
echo.
pause

python navigator.py "!MAP_PNG!" --map "!MAP_JPG!"

echo.
echo   Navigator exited.
pause
