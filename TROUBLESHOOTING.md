# Troubleshooting

Plain-language fixes for the problems you are most likely to see. Try them in order.

---

## The console says "FFmpeg is not available"

FFmpeg is the helper program that merges video and audio and makes MP3s.
The downloader looks for it in this order and uses the first one that **actually runs**:

1. `bin\ffmpeg.exe` + `bin\ffprobe.exe` in this folder (a copy you put there)
2. FFmpeg installed on the computer (on the system PATH)
3. A private copy it downloads itself on first start (~100 MB, one time)

The red banner shows *which* of these failed and why. Fixes, any one is enough:

| Fix | Steps |
|-----|-------|
| **A. Let it download itself** (easiest) | Make sure the PC is online. Close the console window. Run `Start.bat` again. Watch for "FFmpeg ready". |
| **B. Put a copy in the `bin` folder** (works offline, most reliable) | Download the *essentials* zip from https://www.gyan.dev/ffmpeg/builds/ . Open it, go into the `bin` folder inside, copy `ffmpeg.exe` and `ffprobe.exe` into the `bin` folder next to `Start.bat` (create it if needed). Restart the console. |
| **C. Install system-wide** | Open PowerShell, run `winget install Gyan.FFmpeg`, close and reopen the console. |

Specific messages:

- **"... is broken (exit code ...)" / "Exec format error" / "could not run"** — that copy is damaged or the wrong type (e.g. a 32-bit / Mac build). Delete it and use fix A or B.
- **"... has no ffprobe next to it"** — you copied `ffmpeg.exe` but not `ffprobe.exe`. Both are needed; they are in the same zip.
- **"could not download FFmpeg"** — no internet, or a proxy/firewall blocks GitHub. Use fix B from a machine that can download, then copy the two files over.
- **"static-ffmpeg package is not installed"** — the setup step did not finish. Run `Start.bat` again while online.

You can always see which FFmpeg is in use: the console header shows `FFmpeg: bundled`, `system`, or `static-ffmpeg` plus its version. The `bin` folder copy always wins, so putting a known-good copy there overrides a broken system install.

---

## Downloads fail with "HTTP Error 403", "Sign in to confirm you're not a bot", or "Requested format is not available"

YouTube changed something and the downloader needs updating. This happens every few weeks.

1. Click **Update downloader** in the console (or run `Update.bat`).
2. Close the console window and run `Start.bat` again.
3. Retry the download.

If it still fails right after an update, the fix is probably not released yet — try again in a day or two.

---

## Keeping the program up to date

There are two different things that can be updated:

| What | Why | How |
|------|-----|-----|
| **yt-dlp** (the part that talks to YouTube) | YouTube changed something; downloads fail with 403 / "not a bot" / "format not available" | **Update downloader** button, or `Update.bat` |
| **This program** (console, engine, launcher) | New features or fixes were published on GitHub | **Update app** button, the blue banner that appears when a new version exists, or `UpdateApp.bat` |

After either update, close the console window and run `Start.bat` again.

**"Local files have been modified; refusing to overwrite them"** — you (or someone) edited one of the program files.
The updater will not destroy those edits. Either undo them, or open a terminal in the folder and run `git stash`, then update again.

**"Could not check for updates"** — no internet, or GitHub is blocked by a proxy/firewall. Downloads from YouTube may still work. Try `UpdateApp.bat` from a network that can reach github.com.

**Nothing happens after updating** — you must restart: close the black window and run `Start.bat`. The new files are on disk but the running program still has the old ones loaded.

---

## "Sign in to confirm your age" / members-only / private video

The downloader needs your YouTube login cookies.

- **Use Firefox.** Log in to YouTube in Firefox, then start the console with
  `Start.bat --cookies-from-browser firefox`.
- **Chrome and Edge on Windows do not work** for this: since Chrome 127 (mid-2024) they encrypt cookies so that
  other programs cannot read them ("App-Bound Encryption"). yt-dlp will report an error or find no cookies.
  This is not something the downloader can fix.
- If you must use Chrome/Edge: install a "Get cookies.txt LOCALLY" style extension, export `cookies.txt` while
  on youtube.com, and start with `Start.bat --cookies-file C:\path\to\cookies.txt`. Cookies expire; re-export when downloads start failing.
- Close the browser first if you see "database is locked".

---

## "No supported JavaScript runtime could be found" warning

Harmless. Some rarely used formats may be missing, downloads still work. Installing Deno (https://deno.com) removes the warning; it is optional.

---

## The web page does not open / "This site can't be reached"

- Look at the black console window. It must say `Running on http://127.0.0.1:8765`. If it shows an error, read it — usually a dependency failed to install (no internet) or the port is in use.
- Port in use: run `Start.bat --port 8766` and open http://127.0.0.1:8766 .
- Open the address by hand in any browser: http://127.0.0.1:8765

The page only works on this computer. That is deliberate.

---

## "Python was not found"

**Windows:** install Python 3 from https://www.python.org/downloads/windows/ . During setup tick **"Add python.exe to PATH"**. Then run `Start.bat` again.
**macOS:** https://www.python.org/downloads/macos/ or `brew install python`, then double-click `Start.command` again.
**Linux:** `sudo apt install python3 python3-venv` (Debian/Ubuntu), then `./start.sh`.

---

## macOS: "Start.command cannot be opened because it is from an unidentified developer"

Right-click `Start.command`, choose **Open**, then **Open** again in the dialog. macOS remembers the choice. If double-clicking does nothing at all, open Terminal, drag `start.sh` into it and press Enter.

---

## Linux: "ensurepip is not available" / "No module named pip"

`start.sh` works around this automatically by fetching pip itself (needs internet). If it still fails, install the venv package for your Python, e.g. `sudo apt install python3-venv`, delete the `.venv` folder and run `./start.sh` again.

---

## A playlist download says SKIPPED and downloads nothing

Everything in it was already downloaded earlier. The downloader remembers finished items in `downloads\archive_video.txt` and `downloads\archive_audio.txt`.
To download again anyway, delete the relevant line(s) — or the whole file — and retry.

---

## Files are named `... [240p].mp4` when I asked for 1080p

The number in brackets is the resolution that was **actually available**, not what you asked for. That video only exists at 240p on YouTube.

---

## The video plays with no sound / stutters in an old player

High-resolution YouTube video uses the VP9 or AV1 codec with Opus audio. Inside an MP4 file some older players (old Windows Media Player, some TVs and phones) cannot handle that combination. Either play it with VLC, or download again choosing **Format: MKV**, which is the native container for those codecs. Note the in-page **Play** button cannot play MKV - use **Open**.

---

## WAV files are huge / "24-bit" does not sound better

WAV is uncompressed: about 10 MB per minute at 16-bit, 15 MB at 24-bit. YouTube's audio is itself compressed (Opus or AAC, ~128 kbps), so no WAV setting can recover detail that was never there. Choose WAV when a program you use needs it (editing, DAW import); 24-bit gives extra headroom for processing, not more detail. For listening, MP3 320 kbps or "Original audio" is the sensible choice.

---

## A clip is a second or two longer / shorter than I asked

Normal. The cut is made at the nearest video keyframe so the clip does not need to be re-encoded (which keeps it fast and lossless). Ask for a slightly wider range if the exact boundary matters.

---

## "Browse…" does nothing or shows an error

The folder picker is a small system dialog opened on this computer. It can appear *behind* the browser window — check the taskbar. If it is not available at all, just type or paste the folder path into the box and click Save.

---

## A download was interrupted

Just queue it again. Partial `.part` files are resumed, not restarted.

---

## Where things are

| What | Where |
|------|-------|
| Downloaded files | `downloads\` (playlists get their own subfolder) |
| Run log (every attempt, with status) | `download_log.txt` inside the download folder |
| Queue history and chosen folder | `%LOCALAPPDATA%\YouTubeDownloader\history.json` and `settings.json` (shown at the bottom of the page) — safe to delete; kept outside the program folder so reinstalling does not lose them |
| Private Python environment | `.venv\` — safe to delete; `Start.bat` recreates it |
| Downloaded FFmpeg copy | inside `.venv\Lib\site-packages\static_ffmpeg\bin\` |
| Your own FFmpeg copy (optional) | `bin\ffmpeg.exe`, `bin\ffprobe.exe` |

If nothing here helps, send the IT contact the contents of the black console window and the last few lines of `downloads\download_log.txt`.
