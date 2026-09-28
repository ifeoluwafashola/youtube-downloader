@echo off
setlocal
title YouTube Downloader - update app
cd /d "%~dp0"
set "PYTHONUTF8=1"

echo Getting the latest version of this program from GitHub...
echo.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" yt_update.py
) else (
    rem No environment yet - fall back to any system Python.
    where py >nul 2>nul && (py -3 yt_update.py) || (python yt_update.py)
)
echo.
echo If files were updated, run Start.bat to use the new version.
pause
