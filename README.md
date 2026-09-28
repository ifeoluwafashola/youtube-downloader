# YouTube Downloader

A small, self-contained YouTube video and playlist downloader with a browser-based
console, built on [yt-dlp](https://github.com/yt-dlp/yt-dlp). Intended for
non-technical users on Windows: double-click one file and everything else is
handled (Python environment, dependencies, FFmpeg).

## Quick start (Windows)

1. Install Python 3.9 or newer from https://www.python.org/downloads/windows/
   and tick **"Add python.exe to PATH"** during setup.
2. Download or clone this folder.
3. Double-click **`Start.bat`**.

The first run needs internet and takes a couple of minutes: it creates a private
Python environment in `.venv\`, installs the dependencies, and downloads a private
copy of FFmpeg if the computer does not already have one. Later runs start in
seconds. A browser tab opens at http://127.0.0.1:8765 automatically.

Keep the black console window open while downloading; close it to stop.

## Using the console

- Paste a video or playlist link and click **Inspect**. You see the title,
  uploader, duration or the list of videos in the playlist.
- Choose a quality (Best / 4K / 1440p / 1080p / 720p / 480p) or tick
  **Audio only (MP3)**.
- For playlists, download **All**, a **Range** (e.g. 5–20), or **Pick**
  individual videos.
- Links of the form `watch?v=...&list=...` ask whether you want just that video
  or the whole playlist.
- **Add several links at once** lets you paste a list, one per line.
- The queue shows live progress. Finished items list every file with its size,
  a **Play** button (plays right in the page) and an **Open** button (opens it
  in your usual media player). **Show in folder** opens the folder the files
  were saved to, with the file highlighted.
- **Open folder** opens the `downloads\` folder. **Update downloader** upgrades
  yt-dlp when YouTube changes something and downloads start failing.
  **Update app** fetches the latest version of this program from GitHub; a
  banner appears automatically when one is available. Restart afterwards.

Files land in `downloads\`. Playlists get their own subfolder. Every attempt is
recorded in `downloads\download_log.txt`.

## Command line

The same engine is available without the browser:

```
python YtUnified.py                                   interactive menu
python YtUnified.py --url URL [--quality 1080] [--audio] [--items 1-5]
python YtUnified.py --list-formats URL
python YtUnified.py --update
```

Run `python YtUnified.py --help` for all options. Exit codes: 0 success,
1 failure, 2 bad arguments.

## Options for Start.bat

Anything after `Start.bat` is passed to the console, e.g.

```
Start.bat --output D:\Videos
Start.bat --cookies-from-browser firefox
Start.bat --port 8766
```

Cookies are needed for age-restricted, members-only or private videos. See
`TROUBLESHOOTING.md` for details, including why Chrome and Edge cookies do not
work on current Windows builds.

## Folder layout

| File | Purpose |
|------|---------|
| `Start.bat` | Launcher for Windows |
| `Update.bat` | Upgrade yt-dlp |
| `UpdateApp.bat` | Update this program from GitHub |
| `yt_update.py` | Update logic (git pull, or zip download for non-git installs) |
| `yt_web.py` | Web console (Flask, local only) |
| `templates/index.html` | The web page (no internet-hosted assets) |
| `yt_engine.py` | Download engine shared by the console and CLI |
| `YtUnified.py` | Command-line front end |
| `requirements.txt` | Dependencies |
| `tests/` | Unit tests (`python -m pytest tests`) |
| `FEATURES.md` | Feature list and status |
| `TROUBLESHOOTING.md` | Plain-language fixes for common problems |
| `legacy/` | Original scripts, superseded, kept for reference |

## Requirements

- Windows 10/11 with Python 3.9+ (macOS and Linux work too via
  `python yt_web.py`; there is no `.command`/`.sh` launcher yet)
- Internet access on first run (pip packages and FFmpeg)
- FFmpeg: found automatically, downloaded automatically, or supplied by you in
  `bin\ffmpeg.exe` + `bin\ffprobe.exe`

## Notes

- The console binds to 127.0.0.1 only. It is not reachable from other machines.
- Download only content you have the right to download. Respect YouTube's Terms
  of Service and applicable copyright law.
