@echo off
setlocal
chcp 65001 >nul
title Solution Workspace - 生成离线升级包

echo 正在同步 mvp 并生成离线升级包，请稍候...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\New-OfflineUpdateBundle.ps1" -OpenFolder
set "toolExitCode=%ERRORLEVEL%"

if not "%toolExitCode%"=="0" (
    echo.
    echo 生成失败，请保留本窗口的错误信息。
) else (
    echo.
    echo 生成成功，升级包所在文件夹已打开。
)

echo.
pause
exit /b %toolExitCode%
