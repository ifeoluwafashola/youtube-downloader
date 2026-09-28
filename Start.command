#!/usr/bin/env bash
# macOS: double-click this file in Finder to start the YouTube Downloader.
# (Finder runs .command files in Terminal. If macOS says the file cannot be
# opened, right-click it, choose Open, and confirm once.)
cd "$(dirname "$0")"
exec ./start.sh "$@"
