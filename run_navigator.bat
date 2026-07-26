@echo off
cd /d "%~dp0"
call "%USERPROFILE%\miniconda3\Scripts\activate.bat" brain 2>nul
setlocal enabledelayedexpansion

echo ============================================
echo   DeadMaze - Navigation
echo ============================================
echo.

set COUNT=0
for /d %%d in (map\*) do (
    set /a COUNT+=1
    set MAPDIR[!COUNT!]=%%d
    set MAPNAME[!COUNT!]=%%~nxd
)

if %COUNT%==0 (
    echo No maps found. Run map_stitcher or download a map.
    pause
    exit /b
)

echo Available maps:
echo ----------------------------------------
for /l %%i in (1,1,%COUNT%) do (
    set REACH=!MAPDIR[%%i]!\!MAPNAME[%%i]!_reachable.png
    set STATUS=unmarked
    if exist "!REACH!" set STATUS=READY
    echo   [%%i]  !MAPNAME[%%i]!  [!STATUS!]
)
echo ----------------------------------------

set /p CHOICE="Select [1-%COUNT%] (Enter=1): "
if "%CHOICE%"=="" set CHOICE=1
if %CHOICE% gtr %COUNT% set CHOICE=1
if %CHOICE% lss 1 set CHOICE=1

set MAP_JPG=!MAPDIR[%CHOICE%]!\!MAPNAME[%CHOICE%]!.jpg
set MAP_PNG=!MAPDIR[%CHOICE%]!\!MAPNAME[%CHOICE%]!_reachable.png

echo.
echo Launching: !MAPNAME[%CHOICE%]!
echo   JPG: !MAP_JPG!
echo   PNG: !MAP_PNG!
echo.
echo L-click=Start  R-click=Goal  Enter=Go
echo Space=Pause  Esc=Stop  Q=Quit
echo H=Campfire  M=Patrol  1-4=Skills
echo ----------------------------------------
pause

python navigator.py "!MAP_PNG!" --map "!MAP_JPG!"
pause
