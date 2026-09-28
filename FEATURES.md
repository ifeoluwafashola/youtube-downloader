# YouTube Downloader — Feature Tracker

Tracks features, their implementation status, and notes.

## Files

| File | Purpose |
|------|---------|
| `README.md` | Start here: what it is, quick start, usage |
| `TROUBLESHOOTING.md` | Plain-language fixes: FFmpeg, 403s, cookies, page not opening |
| `start.sh` / `Start.command` / `update.sh` | The same for Linux and macOS |
| `Start.bat` | Double-click launcher: sets up a private Python environment, installs dependencies, starts the web console, opens the browser |
| `Update.bat` | Updates the program and yt-dlp (one step) |
| `yt_update.py` | Update logic shared by the batch file and the console button |
| `yt_web.py` | Local web console (Flask, 127.0.0.1:8765) with a download queue |
| `templates/index.html` | The web page — single file, no internet-hosted assets |
| `yt_engine.py` | Headless download engine shared by the console and the CLI; no printing or prompting |
| `YtUnified.py` | Command-line / interactive front end over the engine |
| `requirements.txt` | yt-dlp, flask, static-ffmpeg, mutagen |
| `tests/test_engine.py` | Unit tests for the pure engine functions (`python -m pytest tests`) |
| `legacy/` | Original `YtDownloader2.py` and `YtPlaylist.py`, superseded — kept for reference only |

## Legend
- ✅ Implemented
- 🔲 Planned / not yet implemented
- ⚠️ Partially implemented or has known caveats
- ❌ Dropped

---

## Core Download

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 1 | Merged best-video + best-audio via FFmpeg (true 4K) | ✅ | Falls back to closest available resolution if nothing fits under the cap |
| 1a | Container choice: MP4 or MKV | ✅ | "Format" dropdown for video (default MP4). MKV holds VP9/AV1 + Opus natively with cover art as an attachment; the in-page Play button is hidden for `.mkv` (browsers cannot play it) - use Open. CLI `--container mkv`. Remembered per form; re-download keeps it |
| 2 | Quality selection: best / 2160 / 1440 / 1080 / 720 / 480 | ✅ | Accepts menu numbers 0–5, `1080`, `1080p`, or `best` |
| 3 | "Best available" quality mode | ✅ | Default everywhere; `--quality best` on CLI |
| 4 | Audio-only download | ✅ | MP3 at 320 / 192 / 128 kbps, WAV 16-bit / 24-bit (PCM), or the original stream with no re-encoding (.opus/.m4a). Cover art and tags embedded where the container allows (not WAV). Separate playlist archive per format. Files tagged `[320k]`, `[24-bit]` |
| 5 | Thumbnail embedding | ✅ | mutagen preferred, FFmpeg fallback |
| 6 | Metadata embedding | ✅ | FFmpegMetadata postprocessor |
| 7 | Collision-safe filenames — `title [1080p] (1).mp4` | ✅ | Resolution tag is the *actual* downloaded height, not the cap. Only finished files count as collisions; `.part` / `.fNNN` intermediates are ignored so interrupted downloads resume instead of being renamed |
| 8 | Single network round-trip per video download | ✅ | Metadata from the format-selection pass is reused for the download (same path as `--load-info-json`) |
| 9 | Clip download (start–end timestamp) | ✅ | Console: "Clip" tick box on single videos, times as `mm:ss` / `h:mm:ss` / `90` / `1m30s`; either side may be empty. yt-dlp hands the range to FFmpeg, which fetches only that section (cuts land on keyframes, so a second or two of slack is normal). File is tagged `[1080p 12.00-15.00]` |
| 10 | Format inspection | ✅ | `YtUnified.py --list-formats URL` |
| 11 | Subtitle handling | ❌ | Dropped; Whisper is the better path for caption harvesting |
| 12 | No-FFmpeg fallback (pre-merged single file) | ⚠️ | Still present but YouTube now rarely serves pre-merged formats; a clear error is shown instead of a cryptic yt-dlp message |

## Playlist

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 13 | Playlist vs video auto-detection | ✅ | Flat extraction (`extract_flat: in_playlist`); cookies applied during inspection |
| 14 | `watch?v=…&list=…` disambiguation | ✅ | Console offers "Just this video / Whole playlist"; CLI `--no-playlist`; interactive prompt |
| 15 | Playlist title listing before download | ✅ | |
| 16 | Scope selection — all / range / specific videos | ✅ | `1,3,5-8` or `1 3 5-8`; validated against entry count |
| 17 | Download archive (skip already-downloaded items) | ✅ | Separate `archive_video.txt` / `archive_audio.txt` so an MP3 run does not hide a later video run |
| 18 | Per-playlist subfolder | ✅ | `downloads/<playlist title>/<index> - <title>.<ext>`; playlist cover image no longer written |
| 19 | Accurate outcome for playlists | ✅ | SUCCESS / PARTIAL / FAILED / SKIPPED based on completed count and yt-dlp return code — previously always SUCCESS |

## Reliability and Performance

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 20 | Retry on failure | ✅ | `retries: 10`, `fragment_retries: 10` |
| 21 | Resumed downloads | ✅ | `continuedl: True` (and collision check no longer defeats it) |
| 22 | Concurrent fragment downloads | ✅ | 4 |
| 23 | Progress display (percent, speed, ETA, current item) | ✅ | Computed from byte counts; yt-dlp's own bar suppressed (`noprogress`) so nothing prints twice |
| 24 | FFmpeg auto-provisioning | ✅ | Order: `Yt/bin/` (bundled) → system PATH → `static-ffmpeg` package downloads a private copy once (~100 MB). Path passed to yt-dlp via `ffmpeg_location` |
| 25 | Self-update: one Update for program + yt-dlp | ✅ | Single **Update** button / banner / `Update.bat` / `update.sh`. `yt_update.update_all()` pulls the program (git or zip), reinstalls requirements if changed, then upgrades yt-dlp; reports both. `--check` shows what is behind; `--app-only` exists for scripting |
| 26 | Startup update check + banner | ✅ | Background thread compares the installed commit with GitHub and the installed yt-dlp with PyPI (numeric compare, so `2026.8.19` = `2026.08.19`); one banner names what is behind |
| 26a | Program update mechanics | ✅ | `git pull --ff-only` for clones, otherwise the GitHub zip copied over. `.venv`, `downloads`, `bin`, `.git` never touched; refuses to overwrite real local edits (CRLF-only differences are reset); reinstalls dependencies if `requirements.txt` changed |
| 27 | FFmpeg check is cached | ✅ | Was spawning a subprocess 3–4 times per download |

## Cookies and Authentication

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 28 | Cookies from browser | ✅ | `--cookies-from-browser chrome` (both `yt_web.py` and `YtUnified.py`); interactive prompt |
| 29 | Cookies from file | ✅ | `--cookies-file cookies.txt` |
| 30 | Cookies used for inspection as well as download | ✅ | Previously inspection ran without cookies, so restricted videos failed before the download started |

## Web Console

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 31 | Local Flask server, browser auto-opens | ✅ | Bound to 127.0.0.1 only; `--port`, `--output`, `--no-browser`. State-changing requests must be same-origin JSON, so a web page you visit cannot drive the console (CSRF guard). Console window shows only the status lines - no dev-server banner or per-request log |
| 32 | Inspect URL → show title / uploader / duration / entry list | ✅ | |
| 33 | Per-job quality, audio-only, playlist scope | ✅ | Range inputs or checkbox picker with select all / none |
| 34 | Bulk add (paste several links) | ✅ | Non-YouTube lines are skipped and left in the box; replaces the planned xlsx/txt batch import |
| 35 | Live queue table with progress bars and per-job log | ✅ | Polls `/api/state` every second; background worker processes jobs one at a time. Rows are patched in place (a cell is only re-rendered when it changes), so scroll position and text selection in a log survive refreshes |
| 35a | Copy log button | ✅ | Copies the job's yt-dlp output to the clipboard; last 300 lines kept per job |
| 35b | Logs loaded on demand | ✅ | The once-a-second list carries only a line count; the text comes from `GET /api/jobs/<id>/log` when a panel is opened, and is re-fetched each tick only while that panel is open and the job is running |
| 36 | Remove queued job / clear history | ✅ | |
| 36e | Cancel a running download | ✅ | Engine raises `DownloadCancelled` from its hooks; partial `.part` files stay so a retry resumes |
| 36a | Finished files listed per job with size | ✅ | Total size shown in the status column; lists longer than 5 files collapse behind a summary |
| 36b | Play button (in-page player) | ✅ | Streams from the local server with seeking (HTTP Range); MP4/WebM/MP3/M4A/OGG/Opus. Falls back to a hint if the browser cannot decode the codec |
| 36d | Show in folder button per finished job | ✅ | Opens the job's actual folder (playlist subfolder included) with the file highlighted: `explorer /select,` on Windows, `open -R` on macOS |
| 36c | Open button (default desktop player) | ✅ | `os.startfile` on Windows; only files inside the downloads folder can be opened or streamed |
| 37 | Settings panel | ✅ | Header holds only the title, **Update** and **Settings**; the panel (closed by default) has the download folder (Browse / Save / Open folder) and an About block (program version, yt-dlp, FFmpeg source, where history lives). Header aligned to the content width and stays on one line on narrow windows |
| 38 | Update button | ✅ | One button for program + yt-dlp (see #25) |
| 39 | View run log in page | ✅ | |
| 40 | FFmpeg missing banner with plain-language fix | ✅ | |
| 41 | Windows `Start.bat` launcher | ✅ | Creates `.venv`, installs only when `requirements.txt` changed, launches console |
| 42 | macOS / Linux launchers | ✅ | `start.sh` (tested on Linux incl. a Python without ensurepip - bootstraps pip itself), `Start.command` double-click wrapper for Finder (untested on a Mac), `update.sh` |
| 42a | Launcher self-heals a half-made `.venv` | ✅ | Both `Start.bat` and `start.sh` check that pip works inside the venv and recreate it if not (e.g. after an interrupted first run) |
| 43 | Queue history across restarts | ✅ | `history.json` in the user profile (`%LOCALAPPDATA%\YouTubeDownloader` on Windows), so it survives deleting or re-downloading the program folder; older copies next to the scripts are migrated automatically. Last 500 jobs incl. logs. Jobs that were running when the console closed show as INTERRUPTED. Files are re-checked every 10 s; deleted ones are struck through and the job gets a "Download again" button |
| 43a | Download again | ✅ | Re-queues with the same URL and options and `force=True`: playlist archive ignored, but files still on disk are skipped, so only what is missing is fetched |
| 44 | Choose output folder from the page | ✅ | Settings panel; "Browse…" opens the OS folder picker (tkinter, same machine), or type a path. Saved in `settings.json` in the user profile and used on the next start unless `--output` is given. Default for new installs is `<Downloads>\YouTube Downloader` (an existing `downloads\` next to the scripts keeps being used). Each job remembers the folder it used, so Play/Open/Show in folder keep working after a change |
| 45 | Batch import from .xlsx / .txt | ❌ | Superseded by bulk paste (#34) |
| 46 | Standalone executable (PyInstaller) | 🔲 | |

## Command-Line Interface

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 47 | argparse CLI | ✅ | `--url --quality --audio [FORMAT] --container --output --items --no-playlist --no-ffmpeg --cookies-from-browser --cookies-file --list-formats --update --version` |
| 48 | Exit codes | ✅ | 0 success/skipped, 1 failure, 2 bad arguments, 130 interrupted |
| 49 | Interactive mode honours `--output` and cookie flags | ✅ | Previously hard-coded `./downloads` |
| 50 | `--start` / `--end` clip flags | 🔲 | Engine supports it (`download(start=, end=)`); CLI flags not wired yet |

## Logging

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 51 | Run log | ✅ | `downloads/download_log.txt`, tab-separated via `csv` (titles with tabs/newlines are quoted correctly). Columns: time, status, kind, title, url, count, detail |
| 52 | Statuses | ✅ | SUCCESS, PARTIAL, FAILED, SKIPPED |

## Code Structure

| # | Item | Status | Notes |
|---|------|--------|-------|
| 53 | Engine / UI separation | ✅ | `yt_engine.Downloader` takes `on_message` / `on_progress` callbacks; `Settings` dataclass replaces module globals |
| 54 | One download path instead of four near-duplicate functions | ✅ | `_format_opts()` + `_download_video()` / `_download_playlist()` |
| 55 | Unit tests | ✅ | 58 tests over the pure functions; network paths tested manually |
| 56 | Legacy scripts retired | ✅ | Moved to `legacy/`; not maintained |

---

## Known Issues / External Dependencies

| Issue | Status | Notes |
|-------|--------|-------|
| yt-dlp breaks when YouTube changes its backend | ⚠️ Ongoing | Use the **Update** button or `Update.bat`; `requirements.txt` pins `>=2026.8.19` |
| "No supported JavaScript runtime" warning | ⚠️ External | Some formats may be missing without Deno; downloads still work. Installing Deno is optional |
| 4K files are VP9/AV1 + Opus in an MP4 container | ⚠️ By design | Plays in VLC, Chrome, modern Windows; very old players may need codecs. Choose Format: MKV if a player struggles |
| First run needs internet for pip and the FFmpeg download | ⚠️ | Later runs work offline (apart from YouTube itself) |

---

Prepared by Ife / For IT Department / 11PLC
