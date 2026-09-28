#!/usr/bin/env bash
# macOS / Linux: update the YouTube Downloader - the program (from GitHub)
# and yt-dlp (the part that talks to YouTube) in one go.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    echo "Run ./start.sh once first to set things up."; exit 1
fi
exec .venv/bin/python yt_update.py "$@"
