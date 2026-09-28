@echo off
setlocal
cd /d "%~dp0"
echo Updating yt-dlp (the part that talks to YouTube)...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m pip install --upgrade yt-dlp
) else (
    echo Run Start.bat once first to set things up.
)
echo.
pause
