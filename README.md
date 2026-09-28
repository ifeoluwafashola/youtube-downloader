# YouTube Downloader

A small, self-contained YouTube video and playlist downloader with a browser-based
console, built on [yt-dlp](https://github.com/yt-dlp/yt-dlp). Intended for
non-technical users on Windows: double-click one file and everything else is
handled (Python environment, dependencies, FFmpeg).

## Quick start

### Windows

1. Install Python 3.9 or newer from https://www.python.org/downloads/windows/
   and tick **"Add python.exe to PATH"** during setup.
2. Download or clone this folder.
3. Double-click **`Start.bat`**.

The first run needs internet and takes a couple of minutes: it creates a private
Python environment in `.venv\`, installs the dependencies, and downloads a private
copy of FFmpeg if the computer does not already have one. Later runs start in
seconds. A browser tab opens at http://127.0.0.1:8765 automatically.

Keep the black console window open while downloading; close it to stop.

### macOS

1. Install Python 3 from https://www.python.org/downloads/macos/ (or `brew install python`).
2. Download or clone this folder.
3. Double-click **`Start.command`**. If macOS refuses the first time, right-click
   it, choose *Open*, and confirm once.

### Linux

```
sudo apt install python3 python3-venv      # Debian/Ubuntu; adjust for your distro
./start.sh
```

On all systems the first run needs internet (dependencies and, if the computer
has none, FFmpeg). A browser tab opens at http://127.0.0.1:8765 automatically.

## Using the console

The first visit offers a short tour, and **? Help** (top right) has a plain-language
guide at any time.

- Paste a video or playlist link and click **Inspect**. You see the title,
  uploader, duration or the list of videos in the playlist.
- Choose **Video** and a quality (Best / 4K / 1440p / 1080p / 720p / 480p) and a
  format (MP4 plays everywhere; MKV is the better fit for 4K/VP9/AV1 but does not
  play in the in-page player), or
  **Audio only** and a format: MP3 at 320, 192 or 128 kbps, WAV at 16- or
  24-bit, or the original stream with no conversion. Your last choice is
  remembered.
- For playlists, download **All**, a **Range** (e.g. 5–20), or **Pick**
  individual videos.
- Links of the form `watch?v=...&list=...` ask whether you want just that video
  or the whole playlist.
- Tick **Clip** on a single video to download only part of it, e.g. from
  `12:00` to `15:00`. Leave one side empty for "from the start" / "to the end".
- **Add several links at once** lets you paste a list, one per line.
- The queue shows live progress; a running download can be **Cancelled**.
  Finished items list every file with its size, a **Play** button (plays right
  in the page) and an **Open** button (opens it in your usual media player).
  **Show in folder** opens the folder the files were saved to.
- The list is kept as history across restarts. If a file is later deleted from
  disk it is marked, and **Download again** fetches it once more.
- **Settings** (top right) holds the download folder (**Browse…** opens a normal
  folder picker; the choice is remembered) and shows the program, yt-dlp and
  FFmpeg versions.
- **Update** fetches the latest
  version of this program and of yt-dlp in one go; a banner appears when
  something newer exists. Use it whenever downloads start failing - YouTube
  changes things every few weeks. Click **Restart now** afterwards; the console
  comes back on its own.

Files land in `Downloads\YouTube Downloader` unless you chose another folder.
Playlists get their own subfolder. Every attempt is recorded in
`download_log.txt` inside that folder. History and settings are kept in your
user profile (`%LOCALAPPDATA%\YouTubeDownloader`), so they survive deleting or
re-downloading the program.

## Command line

The same engine is available without the browser:

```
python YtUnified.py                                   interactive menu
python YtUnified.py --url URL [--quality 1080] [--audio [mp3-320|wav-24|...]] [--items 1-5]
python YtUnified.py --list-formats URL
python yt_update.py                                   update program + yt-dlp
```

Run `python YtUnified.py --help` for all options. Exit codes: 0 success,
1 failure, 2 bad arguments.

## Launcher options

Anything after `Start.bat` / `start.sh` is passed to the console, e.g.

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
| `start.sh`, `Start.command` | Launcher for Linux / macOS (`.command` is the double-clickable wrapper) |
| `Update.bat`, `update.sh` | Update the program and yt-dlp |
| `yt_update.py` | Update logic: program (git pull, or zip for non-git installs) + yt-dlp (pip) |
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

- Windows 10/11, macOS, or Linux with Python 3.9+
- Internet access on first run (pip packages and FFmpeg)
- FFmpeg: found automatically, downloaded automatically, or supplied by you in
  `bin\ffmpeg.exe` + `bin\ffprobe.exe`

## Notes

- The console binds to 127.0.0.1 only. It is not reachable from other machines.
- Download only content you have the right to download. Respect YouTube's Terms
  of Service and applicable copyright law.
