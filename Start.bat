@echo off
setlocal EnableExtensions
title YouTube Downloader
cd /d "%~dp0"
rem Make Python print any title, in any language, without crashing.
set "PYTHONUTF8=1"

echo ============================================
echo   YouTube Downloader - starting up
echo ============================================
echo.

rem ---- 1. Find Python 3 ------------------------------------------------------
set "PY="
where py >nul 2>nul && (py -3 -c "import sys" >nul 2>nul && set "PY=py -3")
if not defined PY (where python >nul 2>nul && (python -c "import sys; assert sys.version_info >= (3, 9)" >nul 2>nul && set "PY=python"))
if not defined PY (
    echo Python 3.9 or newer was not found.
    echo.
    echo Install it from https://www.python.org/downloads/windows/
    echo and tick "Add python.exe to PATH" during setup, then run this file again.
    echo.
    pause
    exit /b 1
)

rem ---- 2. Create / reuse a private environment -------------------------------
set "VENV=%~dp0.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "VENVOK=0"
if exist "%VPY%" ("%VPY%" -m pip --version >nul 2>nul && set "VENVOK=1")
if "%VENVOK%"=="0" (
    if exist "%VENV%" (
        echo Previous environment is incomplete - recreating it...
        rmdir /s /q "%VENV%"
    )
    echo First run: creating a private Python environment...
    %PY% -m venv "%VENV%" || (
        rmdir /s /q "%VENV%" 2>nul
        echo.
        echo Could not create the environment. Re-install Python from python.org
        echo with the default options and run this file again.
        pause
        exit /b 1
    )
)

rem ---- 3. Install / refresh dependencies -------------------------------------
rem Only reinstall when requirements.txt changed since the last successful run.
set "STAMP=%VENV%\.requirements.stamp"
set "NEEDINSTALL=1"
if exist "%STAMP%" (
    fc /b requirements.txt "%STAMP%" >nul 2>nul && set "NEEDINSTALL=0"
)
if "%NEEDINSTALL%"=="1" (
    echo Installing / updating components ^(needs internet^)...
    "%VPY%" -m pip install --quiet --upgrade pip
    "%VPY%" -m pip install --quiet --upgrade -r requirements.txt || (
        echo.
        echo Could not install components. Check your internet connection and try again.
        pause
        exit /b 1
    )
    copy /y requirements.txt "%STAMP%" >nul
)

rem ---- 4. Start the console (downloads FFmpeg on first run if needed) --------
echo.
echo Starting the web console. Keep this window open while downloading.
echo Close it (or press Ctrl+C) to stop.
echo.
"%VPY%" yt_web.py %*

echo.
echo The console has stopped.
pause
