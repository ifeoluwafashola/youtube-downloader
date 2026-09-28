@echo off
setlocal
title YouTube Downloader - update
cd /d "%~dp0"
set "PYTHONUTF8=1"

echo Updating the YouTube Downloader...
echo (this fetches the latest program version and the latest yt-dlp)
echo.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" yt_update.py
) else (
    echo Run Start.bat once first to set things up.
)
echo.
pause
