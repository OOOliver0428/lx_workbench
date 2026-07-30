@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-test.ps1" %*
exit /b %ERRORLEVEL%
