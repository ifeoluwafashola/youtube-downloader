#!/usr/bin/env bash
# macOS / Linux: update yt-dlp (the part that talks to YouTube).
# To update the program itself, use:  ./update.sh app
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    echo "Run ./start.sh once first to set things up."; exit 1
fi
if [ "${1:-}" = "app" ]; then
    exec .venv/bin/python yt_update.py
fi
echo "Updating yt-dlp..."
.venv/bin/python -m pip install --upgrade yt-dlp
echo
echo "Done. Restart the console to use the new version."
