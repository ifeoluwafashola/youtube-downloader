#!/usr/bin/env bash
# YouTube Downloader - launcher for macOS and Linux (equivalent of Start.bat).
#
#   ./start.sh                 start the web console
#   ./start.sh --port 8766     any arguments are passed to yt_web.py
#
# First run: creates a private Python environment in .venv, installs the
# dependencies, and downloads FFmpeg if the system has none. Later runs start
# in seconds. macOS users can double-click Start.command instead.

set -euo pipefail
cd "$(dirname "$0")"
export PYTHONUTF8=1

echo "============================================"
echo "  YouTube Downloader - starting up"
echo "============================================"
echo

# ---- 1. Find Python 3.9+ -----------------------------------------------------
PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
        PY="$candidate"; break
    fi
done
if [ -z "$PY" ]; then
    echo "Python 3.9 or newer was not found."
    echo
    if [ "$(uname)" = "Darwin" ]; then
        echo "Install it from https://www.python.org/downloads/macos/ (or: brew install python)"
    else
        echo "Install it with your package manager, e.g.  sudo apt install python3 python3-venv"
    fi
    echo "then run this again."
    read -r -p "Press Enter to close." _ || true
    exit 1
fi

# ---- 2. Create / reuse a private environment ---------------------------------
VENV=".venv"
VPY="$VENV/bin/python"
venv_ok() { [ -x "$VPY" ] && "$VPY" -m pip --version >/dev/null 2>&1; }

if ! venv_ok; then
    [ -d "$VENV" ] && { echo "Previous environment is incomplete - recreating it..."; rm -rf "$VENV"; }
    echo "First run: creating a private Python environment..."
    if ! "$PY" -m venv "$VENV" >/dev/null 2>&1; then
        # Debian/Ubuntu ship Python without ensurepip. Make the environment
        # without pip, then fetch pip directly (needs internet).
        rm -rf "$VENV"
        if "$PY" -m venv --without-pip "$VENV" &&
           "$VPY" -c 'import urllib.request; urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", ".venv/get-pip.py")' &&
           "$VPY" "$VENV/get-pip.py" --quiet; then
            rm -f "$VENV/get-pip.py"
        else
            rm -rf "$VENV"
            echo
            echo "Could not create the environment."
            [ "$(uname)" != "Darwin" ] && echo "On Debian/Ubuntu run:  sudo apt install python3-venv  and try again."
            read -r -p "Press Enter to close." _ || true
            exit 1
        fi
    fi
fi

# ---- 3. Install / refresh dependencies (only when requirements.txt changed) --
install_requirements() {
    STAMP="$VENV/.requirements.stamp"
    if [ ! -f "$STAMP" ] || ! cmp -s requirements.txt "$STAMP"; then
        echo "Installing / updating components (needs internet)..."
        "$VPY" -m pip install --quiet --upgrade pip
        if ! "$VPY" -m pip install --quiet --upgrade -r requirements.txt; then
            echo
            echo "Could not install components. Check your internet connection and try again."
            read -r -p "Press Enter to close." _ || true
            exit 1
        fi
        cp requirements.txt "$STAMP"
    fi
}

# ---- 4. Start the console (downloads FFmpeg on first run if needed) ----------
# Exit code 3 means the user clicked Restart after an update: re-check the
# requirements and start again in the same window.
export YTDL_LAUNCHER=1
echo
echo "Starting the web console. Keep this window open while downloading."
echo "Press Ctrl+C to stop."
echo
while :; do
    install_requirements
    set +e
    "$VPY" yt_web.py "$@"
    code=$?
    set -e
    [ "$code" -eq 3 ] || exit "$code"
    echo
    echo "Restarting..."
    echo
done
