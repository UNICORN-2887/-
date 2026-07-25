@echo off
chcp 65001 >nul
title DeadMaze 导航
echo.
echo ============================================
echo   DeadMaze 导航 & 战斗
echo ============================================
echo.
echo   启动前请确认:
echo   [*] OBS 虚拟摄像头已开启 (1920x1080)
echo   [*] DeadMaze 游戏已运行
echo   [*] 已通过 "1配置.bat" 完成标定
echo ============================================
echo.
echo   操作提示:
echo   左键=起点 | 右键=终点 | Enter=开始导航
echo   空格=暂停 | Esc=停止 | Q=退出
echo   H=返航 | M=循环巡逻 | 1-4=技能
echo ============================================
echo.

:: 启动导航
python navigator.py map_output_reachable.png --map map_output.jpg

pause
