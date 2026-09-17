@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\New-OfflineUpdateBundle.ps1" %*
set "bundleExitCode=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %bundleExitCode%
