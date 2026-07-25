@echo off
chcp 65001 >nul
title DeadMaze 配置中心
echo.
echo ============================================
echo   DeadMaze 配置 & 标定中心
echo ============================================
echo.
echo   正在启动网页配置面板...
echo.
echo   浏览器将自动打开 http://127.0.0.1:5050
echo   按 Ctrl+C 退出
echo ============================================
echo.

:: 自动打开浏览器
start "" http://127.0.0.1:5050

:: 启动配置服务
python config_server.py

pause
