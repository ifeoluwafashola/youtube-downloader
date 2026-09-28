#!/usr/bin/env python3
"""
yt_engine.py - headless YouTube download engine built on yt-dlp.

Shared by the command-line tool (YtUnified.py) and the web console (yt_web.py).
Nothing in this module prints or reads from the terminal: every message and
progress update goes through the callbacks handed to Downloader, so the same
code can drive a terminal, a web page, or a test.

Install dependencies:  pip install -r requirements.txt
"""

from __future__ import annotations

import csv
import glob
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse, parse_qs

try:
    import yt_dlp
except ImportError:  # pragma: no cover - environment problem, not a code path
    raise SystemExit(
        "yt-dlp is not installed.\n"
        "Run:  pip install -r requirements.txt   (or: pip install yt-dlp)"
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUALITIES = ("best", "2160", "1440", "1080", "720", "480")
QUALITY_LABELS = {
    "best": "Best available",
    "2160": "2160p (4K)",
    "1440": "1440p (2K)",
    "1080": "1080p (Full HD)",
    "720": "720p (HD)",
    "480": "480p (SD)",
}
# Menu shortcuts accepted by normalize_quality(); "0" is best.
QUALITY_MENU = {"0": "best", "1": "2160", "2": "1440", "3": "1080", "4": "720", "5": "480"}

# Extensions that count as a finished download when checking for name
# collisions. Intermediate files (.part, .ytdl, .f137.mp4, .webp) do not.
FINAL_EXTS = {"mp4", "mkv", "webm", "mov", "m4a", "mp3", "opus", "ogg", "flac", "wav", "aac"}

YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtu.be", "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com",
}

STATUS_SUCCESS = "SUCCESS"
STATUS_PARTIAL = "PARTIAL"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED = "SKIPPED"


# ---------------------------------------------------------------------------
# Small helpers (pure functions - easy to unit test)
# ---------------------------------------------------------------------------

def normalize_quality(value) -> Optional[str]:
    """
    Turn user input into a canonical quality string.

    Accepts menu numbers ("0"-"5"), resolutions ("1080", "1080p"), or "best".
    Returns None if the input is not recognised.
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    if text.endswith("p") and text[:-1].isdigit():
        text = text[:-1]
    text = QUALITY_MENU.get(text, text)
    return text if text in QUALITIES else None


def is_youtube_url(url: str) -> bool:
    """True if the URL's hostname is a YouTube domain (not a substring check)."""
    try:
        host = (urlparse(url.strip()).hostname or "").lower()
    except ValueError:
        return False
    return host in YOUTUBE_HOSTS or host.endswith(".youtube.com")


def is_video_in_playlist_url(url: str) -> bool:
    """True for watch?v=...&list=... URLs, which could mean either the video or the list."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    query = parse_qs(parsed.query)
    return "list" in query and ("v" in query or parsed.netloc.endswith("youtu.be"))


def parse_selection(raw: str, total: int) -> tuple[Optional[str], list[str]]:
    """
    Turn a user selection into a yt-dlp playlist_items string.

    Accepts comma or space separated numbers and ranges, e.g.
    '1,2,3', '1 2 3', '5-20', '1,3,5-8'.

    Returns (items, warnings). items is a normalised comma-separated string,
    "" if raw was empty (meaning "all"), or None if nothing valid was given.
    """
    raw = (raw or "").strip()
    if not raw:
        return "", []
    valid, warnings = [], []
    for tok in raw.replace(",", " ").split():
        if "-" in tok:
            a, _, b = tok.partition("-")
            if a.isdigit() and b.isdigit() and 1 <= int(a) <= int(b) <= total:
                valid.append(f"{int(a)}-{int(b)}")
            else:
                warnings.append(f"Ignoring invalid range: {tok}")
        elif tok.isdigit() and 1 <= int(tok) <= total:
            valid.append(str(int(tok)))
        else:
            warnings.append(f"Ignoring invalid entry: {tok}")
    return (",".join(valid) if valid else None), warnings


def format_duration(seconds) -> str:
    """Render seconds as m:ss or h:mm:ss; empty string if unknown."""
    if not seconds:
        return ""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


@dataclass
class FFmpegStatus:
    available: bool
    location: Optional[str]     # directory to pass as yt-dlp 'ffmpeg_location', or None for PATH
    source: str                 # "bundled" | "system" | "static-ffmpeg" | "missing"
    detail: str = ""            # where it was found, or why each candidate was rejected
    version: str = ""
    fix: list[str] = field(default_factory=list)   # plain-language steps when not available

    def to_dict(self) -> dict:
        return asdict(self)


BASE_DIR = Path(__file__).resolve().parent
BUNDLED_FFMPEG_DIR = BASE_DIR / "bin"
_EXE = ".exe" if sys.platform == "win32" else ""
_ffmpeg_status: Optional[FFmpegStatus] = None
_ffmpeg_lock = threading.Lock()

FFMPEG_FIX_STEPS = [
    "Make sure this computer is online, close the console and run Start.bat again - "
    "it downloads a private copy of FFmpeg automatically.",
    f"Or download FFmpeg yourself (https://www.gyan.dev/ffmpeg/builds/ - 'essentials' zip), "
    f"and copy ffmpeg.exe and ffprobe.exe into: {BUNDLED_FFMPEG_DIR}",
    "Or install it system-wide: open PowerShell and run  winget install Gyan.FFmpeg  , then restart the console.",
    "If FFmpeg is installed but shown as broken above, uninstall/reinstall it or use one of the two options above; "
    "the bin folder copy always takes priority.",
]


def _probe_ffmpeg(exe: str) -> tuple[bool, str]:
    """
    Run 'ffmpeg -version' once to make sure the binary actually works
    (not a 0-byte file, wrong architecture, missing DLL, ...).
    Returns (ok, version-or-error).
    """
    try:
        proc = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        return False, "file not found"
    except PermissionError:
        return False, "not executable (permission denied)"
    except subprocess.TimeoutExpired:
        return False, "did not respond within 15 s"
    except OSError as e:
        return False, f"could not run: {e}"
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip().splitlines()
        return False, f"exit code {proc.returncode}" + (f": {err[0]}" if err else "")
    first = (proc.stdout or "").splitlines()
    return True, first[0].replace("ffmpeg version ", "").split(" Copyright")[0] if first else "ok"


def _check_candidate(directory: Optional[Path], exe: str, source: str, rejected: list[str]) -> Optional[FFmpegStatus]:
    """Validate one ffmpeg (and its sibling ffprobe); record the reason if rejected."""
    ok, note = _probe_ffmpeg(exe)
    if not ok:
        rejected.append(f"{source} FFmpeg at {exe} is broken ({note})")
        return None
    probe = Path(exe).with_name(f"ffprobe{_EXE}")
    if not probe.is_file() and not (directory is None and shutil.which("ffprobe")):
        rejected.append(f"{source} FFmpeg at {exe} has no ffprobe next to it (needed for MP3 and thumbnails)")
        return None
    return FFmpegStatus(True, str(directory) if directory else None, source,
                        detail=f"{exe}; " + "; ".join(rejected) if rejected else exe, version=note)


def ensure_ffmpeg(fetch: bool = True, on_message: Optional[Callable[[str], None]] = None) -> FFmpegStatus:
    """
    Locate a *working* FFmpeg, in order of preference:
      1. bundled binaries in Yt/bin/ (ffmpeg + ffprobe)
      2. ffmpeg on the system PATH
      3. the static-ffmpeg pip package (downloads binaries once on first use)
    Each candidate is test-run once; a broken one is skipped and the reason kept
    in .detail. The answer is cached for the life of the process once found.
    fetch=False skips the network download in step 3.
    """
    global _ffmpeg_status
    with _ffmpeg_lock:
        if _ffmpeg_status and _ffmpeg_status.available:
            return _ffmpeg_status
        say = on_message or (lambda _m: None)
        rejected: list[str] = []

        def missing(reason: str) -> FFmpegStatus:
            why = "; ".join(rejected + [reason]) if rejected else reason
            return FFmpegStatus(False, None, "missing", why, fix=list(FFMPEG_FIX_STEPS))

        bundled = BUNDLED_FFMPEG_DIR / f"ffmpeg{_EXE}"
        if bundled.is_file():
            status = _check_candidate(BUNDLED_FFMPEG_DIR, str(bundled), "bundled", rejected)
            if status:
                _ffmpeg_status = status
                return status

        system = shutil.which("ffmpeg")
        if system:
            status = _check_candidate(None, system, "system", rejected)
            if status:
                _ffmpeg_status = status
                return status

        try:
            import static_ffmpeg.run as sf  # optional dependency
        except ImportError:
            _ffmpeg_status = missing("FFmpeg not found and the static-ffmpeg package is not installed "
                                     "(run Start.bat to install it)")
            return _ffmpeg_status

        cached = Path(sf.get_platform_dir()) / f"ffmpeg{_EXE}"
        if cached.is_file():
            status = _check_candidate(cached.parent, str(cached), "static-ffmpeg", rejected)
            if status:
                _ffmpeg_status = status
                return status

        if not fetch:
            _ffmpeg_status = missing("no working FFmpeg found and download not attempted")
            return _ffmpeg_status

        try:
            say("No working FFmpeg found - downloading a private copy (one time, ~100 MB)...")
            ffmpeg_path, _ffprobe_path = sf.get_or_fetch_platform_executables_else_raise()
        except Exception as e:  # network down, unsupported platform, ...
            _ffmpeg_status = missing(f"could not download FFmpeg ({e})")
            return _ffmpeg_status
        status = _check_candidate(Path(ffmpeg_path).parent, ffmpeg_path, "static-ffmpeg", rejected)
        if status:
            say(f"FFmpeg ready: {ffmpeg_path}")
            _ffmpeg_status = status
        else:
            _ffmpeg_status = missing("the downloaded FFmpeg does not run on this computer")
        return _ffmpeg_status


def ffmpeg_available() -> bool:
    """True if FFmpeg has been located (does not trigger a download)."""
    return ensure_ffmpeg(fetch=False).available


def ffmpeg_location() -> Optional[str]:
    """Directory to give yt-dlp as ffmpeg_location, or None to use PATH."""
    return ensure_ffmpeg(fetch=False).location


def ytdlp_version() -> str:
    return yt_dlp.version.__version__


def update_ytdlp() -> tuple[bool, str]:
    """
    Upgrade yt-dlp in the current interpreter's environment.
    Returns (ok, pip output). A restart is needed for the new version to load.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
        capture_output=True, text=True,
    )
    output = (proc.stdout + "\n" + proc.stderr).strip()
    return proc.returncode == 0, output


def unique_stem(directory: Path, stem: str) -> str:
    """
    Return stem, or 'stem (N)', such that no *finished* file named
    '<stem>.<ext>' exists in directory. Intermediate files such as
    'stem.mp4.part' or 'stem.f137.mp4' are ignored so that an interrupted
    download can be resumed instead of being renamed.
    """
    def taken(candidate: str) -> bool:
        pattern = glob.escape(str(directory / candidate)) + ".*"
        for path in glob.glob(pattern):
            rest = Path(path).name[len(candidate) + 1:]
            if rest.lower() in FINAL_EXTS:
                return True
        return False

    candidate, n = stem, 1
    while taken(candidate):
        candidate = f"{stem} ({n})"
        n += 1
    return candidate


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    """Everything that varies between runs but not between downloads."""
    output_dir: Path = Path("downloads")
    cookies_from_browser: Optional[str] = None   # e.g. "chrome", "firefox", "edge"
    cookies_file: Optional[Path] = None          # path to a Netscape cookies.txt
    use_ffmpeg: bool = True                      # user preference; see .ffmpeg
    audio_bitrate: str = "192"                   # kbps for MP3 extraction

    def __post_init__(self):
        self.output_dir = Path(self.output_dir).expanduser()
        if self.cookies_file:
            self.cookies_file = Path(self.cookies_file).expanduser()

    @property
    def ffmpeg(self) -> bool:
        """Effective FFmpeg availability: wanted AND installed."""
        return self.use_ffmpeg and ffmpeg_available()

    @property
    def log_file(self) -> Path:
        return self.output_dir / "download_log.txt"

    def cookie_opts(self) -> dict:
        if self.cookies_from_browser:
            return {"cookiesfrombrowser": (self.cookies_from_browser.lower(),)}
        if self.cookies_file and self.cookies_file.is_file():
            return {"cookiefile": str(self.cookies_file)}
        return {}


@dataclass
class Entry:
    index: int
    title: str
    url: str = ""
    duration: Optional[int] = None


@dataclass
class MediaInfo:
    """What inspect() learns about a URL before anything is downloaded."""
    kind: str                       # "video" or "playlist"
    url: str
    title: str
    uploader: str = ""
    duration: Optional[int] = None  # seconds, videos only
    count: int = 1
    entries: list[Entry] = field(default_factory=list)
    mixed_url: bool = False         # watch?v=..&list=.. - could be either
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def duration_text(self) -> str:
        return format_duration(self.duration)

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("raw", None)
        data["duration_text"] = self.duration_text
        return data


@dataclass
class Progress:
    """One progress update. percent is None when the total size is unknown."""
    status: str                     # downloading | finished | postprocessing
    percent: Optional[float] = None
    speed: str = ""
    eta: str = ""
    filename: str = ""
    item_index: Optional[int] = None
    item_count: Optional[int] = None
    item_title: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Result:
    status: str                     # SUCCESS | PARTIAL | FAILED | SKIPPED
    completed: int = 0
    failed: int = 0
    detail: str = ""
    files: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in (STATUS_SUCCESS, STATUS_PARTIAL)

    def to_dict(self) -> dict:
        return asdict(self)


class EngineError(Exception):
    """Raised for problems the engine can explain (bad URL, nothing found, ...)."""


# ---------------------------------------------------------------------------
# yt-dlp logger adapter
# ---------------------------------------------------------------------------

class _Logger:
    """
    Receives yt-dlp's screen output and forwards it to a callback.
    yt-dlp routes ordinary status lines through debug(); true debug lines
    are prefixed with '[debug] ' and are dropped here.
    """

    def __init__(self, sink: Callable[[str], None]):
        self.sink = sink
        self.errors = 0

    def debug(self, msg):
        if not msg.startswith("[debug] "):
            self.sink(msg)

    def info(self, msg):
        self.sink(msg)

    def warning(self, msg):
        self.sink(msg)

    def error(self, msg):
        self.errors += 1
        self.sink(msg)


def _clean_error(exc: BaseException) -> str:
    text = str(exc).strip()
    for prefix in ("ERROR: ", "\x1b[0;31mERROR:\x1b[0m "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.splitlines()[0] if text else type(exc).__name__


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------

MessageCallback = Callable[[str], None]
ProgressCallback = Callable[[Progress], None]


class Downloader:
    """
    Inspects and downloads URLs. One download runs at a time per instance.

    on_message receives human-readable log lines (yt-dlp's output plus ours).
    on_progress receives Progress objects during downloads.
    """

    RELIABILITY = {
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "continuedl": True,
    }

    def __init__(self, settings: Optional[Settings] = None,
                 on_message: Optional[MessageCallback] = None,
                 on_progress: Optional[ProgressCallback] = None):
        self.settings = settings or Settings()
        self.on_message = on_message or (lambda _m: None)
        self.on_progress = on_progress or (lambda _p: None)
        self._lock = threading.Lock()
        self._completed: list[str] = []
        self._last_pp_event = None

    # -- option builders ----------------------------------------------------

    def _common_opts(self, logger: Optional[_Logger] = None) -> dict:
        opts = dict(self.RELIABILITY)
        opts.update(self.settings.cookie_opts())
        if self.settings.ffmpeg:
            location = ffmpeg_location()
            if location:
                opts["ffmpeg_location"] = location
        opts["logger"] = logger or _Logger(self.on_message)
        opts["noprogress"] = True             # we render progress ourselves
        opts["progress_hooks"] = [self._progress_hook]
        opts["postprocessor_hooks"] = [self._pp_hook]
        return opts

    def _format_opts(self, quality: str, audio: bool) -> dict:
        ffmpeg = self.settings.ffmpeg
        if audio:
            opts = {"format": "bestaudio/best"}
            if ffmpeg:
                opts["writethumbnail"] = True
                opts["postprocessors"] = [
                    {"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                     "preferredquality": self.settings.audio_bitrate},
                    {"key": "FFmpegMetadata"},
                    {"key": "EmbedThumbnail"},
                ]
            return opts

        cap = "" if quality == "best" else f"[height<={quality}]"
        if ffmpeg:
            # If nothing fits under the cap, take the smallest thing above it
            # rather than failing or silently jumping to the maximum.
            fmt = f"bestvideo{cap}+bestaudio/best{cap}/worstvideo+bestaudio/worst"
            return {
                "format": fmt,
                "merge_output_format": "mp4",
                "writethumbnail": True,
                "postprocessors": [{"key": "FFmpegMetadata"}, {"key": "EmbedThumbnail"}],
            }
        # Without FFmpeg only pre-merged single files are possible. YouTube
        # now serves very few of these (often just 360p).
        return {"format": f"best{cap}/worst"}

    # -- hooks ----------------------------------------------------------------

    def _progress_hook(self, d: dict):
        info = d.get("info_dict") or {}
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        done = d.get("downloaded_bytes")
        percent = (done / total * 100) if (total and done is not None) else None
        speed, eta = d.get("speed"), d.get("eta")
        self.on_progress(Progress(
            status=d.get("status", ""),
            percent=percent,
            speed=f"{yt_dlp.utils.format_bytes(speed)}/s" if speed else "",
            eta=yt_dlp.utils.formatSeconds(eta) if eta is not None else "",
            filename=Path(d.get("filename") or "").name,
            item_index=info.get("playlist_index"),
            item_count=info.get("playlist_count") or info.get("n_entries"),
            item_title=info.get("title") or "",
        ))

    def _pp_hook(self, d: dict):
        info = d.get("info_dict") or {}
        pp = d.get("postprocessor", "")
        # yt-dlp registers hooks twice on postprocessors declared in params,
        # so identical consecutive events are collapsed here.
        key = (pp, d.get("status"), info.get("id"), info.get("playlist_index"))
        if key == self._last_pp_event:
            return
        self._last_pp_event = key

        if d.get("status") == "started" and pp != "MoveFiles":
            self.on_progress(Progress(
                status="postprocessing", filename=pp,
                item_index=info.get("playlist_index"),
                item_count=info.get("playlist_count") or info.get("n_entries"),
                item_title=info.get("title") or "",
            ))
        # MoveFiles is the final step yt-dlp runs for every successfully
        # downloaded item, so counting it gives an accurate completion count.
        if d.get("status") == "finished" and pp == "MoveFiles":
            self._completed.append(info.get("filepath") or info.get("_filename") or "")

    # -- public API -----------------------------------------------------------

    def inspect(self, url: str, noplaylist: bool = False) -> MediaInfo:
        """
        Work out what a URL is without downloading anything.
        Uses the configured cookies so restricted content can be inspected.
        Raises EngineError if yt-dlp cannot make sense of the URL.
        """
        url = url.strip()
        if not url:
            raise EngineError("No URL given.")
        opts = self._common_opts()
        opts.update({"extract_flat": "in_playlist", "noplaylist": noplaylist,
                     "skip_download": True})
        opts.pop("progress_hooks", None)
        opts.pop("postprocessor_hooks", None)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as e:
            raise EngineError(_clean_error(e)) from e
        if not info:
            raise EngineError("yt-dlp returned no information for this URL.")

        mixed = is_video_in_playlist_url(url)
        if info.get("_type") == "playlist" or info.get("entries") is not None:
            entries = []
            for i, e in enumerate(info.get("entries") or [], start=1):
                if not e:
                    continue
                entries.append(Entry(
                    index=e.get("playlist_index") or i,
                    title=e.get("title") or e.get("url") or "Unknown",
                    url=e.get("url") or e.get("webpage_url") or "",
                    duration=e.get("duration"),
                ))
            return MediaInfo(
                kind="playlist", url=url,
                title=info.get("title") or "Unknown Playlist",
                uploader=info.get("uploader") or info.get("channel") or "",
                count=info.get("playlist_count") or len(entries),
                entries=entries, mixed_url=mixed, raw=info,
            )
        return MediaInfo(
            kind="video", url=url,
            title=info.get("title") or "video",
            uploader=info.get("uploader") or info.get("channel") or "",
            duration=info.get("duration"), count=1, mixed_url=mixed, raw=info,
        )

    def list_formats(self, url: str) -> str:
        """Return yt-dlp's format table for a URL as text."""
        lines: list[str] = []
        opts = self._common_opts(_Logger(lines.append))
        opts.update({"listformats": True, "skip_download": True})
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as e:
            raise EngineError(_clean_error(e)) from e
        return "\n".join(lines)

    def download(self, url: str, *, kind: Optional[str] = None, quality: str = "best",
                 audio: bool = False, items: str = "", noplaylist: bool = False,
                 title: str = "") -> Result:
        """
        Download a video or playlist and append a line to the run log.

        kind: "video" or "playlist"; inspected automatically if None.
        quality: one of QUALITIES (ignored when audio=True).
        items: yt-dlp playlist_items string, "" for all (playlists only).
        noplaylist: for watch?v=..&list=.. URLs, download just the video.
        """
        quality = normalize_quality(quality) or "best"
        with self._lock:
            self._completed = []
            self._last_pp_event = None
            logger = _Logger(self.on_message)
            self.settings.output_dir.mkdir(parents=True, exist_ok=True)
            try:
                if kind is None or not title:
                    info = self.inspect(url, noplaylist=noplaylist)
                    kind, title = kind or info.kind, title or info.title
                if kind == "playlist":
                    retcode = self._download_playlist(url, quality, audio, items, logger)
                else:
                    retcode = self._download_video(url, quality, audio, logger)
            except (yt_dlp.utils.DownloadError, EngineError) as e:
                detail = _clean_error(e)
                if "Requested format is not available" in detail and not audio and not self.settings.ffmpeg:
                    detail = ("No pre-merged video format available. FFmpeg is required to "
                              "download this video - install it and add it to PATH.")
                result = Result(STATUS_FAILED, detail=detail,
                                completed=len(self._completed), files=list(self._completed))
            except Exception as e:  # unexpected - still record it rather than crash the caller
                result = Result(STATUS_FAILED, detail=f"{type(e).__name__}: {e}",
                                completed=len(self._completed), files=list(self._completed))
            else:
                result = self._summarize(retcode, logger.errors)
            self._log(url, title or "Unknown", kind or "unknown", result)
            return result

    # -- download paths -------------------------------------------------------

    def _download_video(self, url, quality, audio, logger) -> int:
        out = self.settings.output_dir
        opts = self._common_opts(logger)
        opts.update(self._format_opts(quality, audio))
        opts["noplaylist"] = True

        # Pass 1: resolve metadata and select the format, so the filename can
        # carry the *actual* height and be checked for collisions.
        with yt_dlp.YoutubeDL(dict(opts, outtmpl=str(out / "%(title)s.%(ext)s"))) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info or info.get("_type") == "playlist":
            raise EngineError("URL resolved to a playlist, not a single video.")

        title = info.get("title") or "video"
        safe_title = yt_dlp.utils.sanitize_filename(title, restricted=False)
        tag = "" if audio else (f"{info['height']}p" if info.get("height") else f"{quality}p")
        stem = unique_stem(out, f"{safe_title} [{tag}]" if tag else safe_title)
        opts["outtmpl"] = str(out / f"{stem}.%(ext)s")

        # Pass 2: download using the already-fetched info (same path yt-dlp
        # uses for --load-info-json), avoiding a second network round-trip.
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.process_ie_result(ydl.sanitize_info(info, remove_private_keys=True), download=True)
        return 0

    def _download_playlist(self, url, quality, audio, items, logger) -> int:
        out = self.settings.output_dir
        opts = self._common_opts(logger)
        opts.update(self._format_opts(quality, audio))
        mode = "audio" if audio else "video"
        opts.update({
            "outtmpl": {
                "default": str(out / "%(playlist_title)s" / "%(playlist_index)s - %(title)s.%(ext)s"),
                # Empty template = do not write the playlist's own thumbnail file.
                "pl_thumbnail": "",
            },
            # Separate archives per mode so an MP3 run does not hide a later video run.
            "download_archive": str(out / f"archive_{mode}.txt"),
            # Skip unavailable items but still report failure via the return code.
            "ignoreerrors": "only_download",
        })
        if items:
            opts["playlist_items"] = items
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.download([url])

    # -- bookkeeping ----------------------------------------------------------

    def _summarize(self, retcode: int, errors: int) -> Result:
        done = len(self._completed)
        files = list(self._completed)
        if retcode == 0 and done == 0:
            return Result(STATUS_SKIPPED, detail="Nothing new to download (already downloaded).", files=files)
        if retcode == 0:
            return Result(STATUS_SUCCESS, completed=done, files=files)
        if done > 0:
            return Result(STATUS_PARTIAL, completed=done, failed=max(errors, 1),
                          detail=f"{max(errors, 1)} item(s) failed", files=files)
        return Result(STATUS_FAILED, failed=max(errors, 1), detail="All items failed", files=files)

    def _log(self, url: str, title: str, kind: str, result: Result):
        """Append one tab-separated, properly quoted line to the run log."""
        try:
            self.settings.log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.settings.log_file, "a", encoding="utf-8", newline="") as fh:
                csv.writer(fh, delimiter="\t", lineterminator="\n").writerow([
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    result.status, kind, title, url,
                    f"{result.completed} done" if result.completed else "",
                    result.detail,
                ])
        except OSError as e:
            self.on_message(f"Warning: could not write to log: {e}")
