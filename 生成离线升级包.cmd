@echo off
rem Solution Workspace offline update bundle generator.
rem Wraps scripts/New-OfflineUpdateBundle.ps1; run from the repository root.
rem The tool syncs origin/main by default, builds a small incremental bundle
rem from the v0.1.0 release baseline, and writes SHA-256 checksums plus a
rem step-by-step upgrade note under outputs\offline-updates\.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\New-OfflineUpdateBundle.ps1" %*
exit /b %errorlevel%
