#!/usr/bin/env python3
"""
yt_web.py - local web console for yt_engine.

    python yt_web.py [--port 8765] [--output ./downloads] [--no-browser]
                     [--cookies-from-browser chrome | --cookies-file cookies.txt]

Starts a Flask server bound to 127.0.0.1 only (never reachable from other
machines), opens the default browser, and processes a download queue on a
background worker thread. Start.bat wraps this for non-technical users.
"""

from __future__ import annotations

import argparse
import itertools
import json
import mimetypes
import os
import platform
import subprocess
import threading
import time
import webbrowser
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from flask import Flask, abort, jsonify, render_template, request, send_file
except ImportError:  # pragma: no cover
    raise SystemExit("Flask is not installed. Run:  pip install -r requirements.txt")

from yt_update import check_for_update, current_version, update_app
from yt_engine import (
    QUALITIES, QUALITY_LABELS,
    Downloader, EngineError, Progress, Settings,
    ensure_ffmpeg, is_youtube_url, normalize_quality, parse_selection, parse_timestamp,
    update_ytdlp, ytdlp_version,
)

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))


# ---------------------------------------------------------------------------
# Queue model
# ---------------------------------------------------------------------------

def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


QUEUED, INSPECTING, DOWNLOADING = "QUEUED", "INSPECTING", "DOWNLOADING"
INTERRUPTED = "INTERRUPTED"          # console was closed while this job was running
TERMINAL = {"SUCCESS", "PARTIAL", "FAILED", "SKIPPED", "CANCELLED", INTERRUPTED}
PLAYABLE = {".mp4", ".webm", ".mp3", ".m4a", ".ogg", ".opus"}

HISTORY_FILE = BASE_DIR / "history.json"
SETTINGS_FILE = BASE_DIR / "settings.json"
HISTORY_LIMIT = 500


@dataclass
class Job:
    id: int
    url: str
    quality: str = "best"
    audio: bool = False
    items: str = ""
    noplaylist: bool = False
    start: Optional[float] = None    # clip boundaries in seconds (single videos)
    end: Optional[float] = None
    force: bool = False              # re-download: ignore the playlist archive
    kind: Optional[str] = None       # filled by inspect if not supplied
    title: str = ""
    output_dir: str = ""             # folder in effect when the job ran
    status: str = QUEUED
    percent: Optional[float] = None
    speed: str = ""
    eta: str = ""
    current: str = ""                # "3/12  Some title" or post-processor name
    detail: str = ""
    completed: int = 0
    files: list = field(default_factory=list)   # [{index, name, path, size, size_text, playable, exists}]
    total_size: int = 0
    added: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    finished: str = ""
    log: deque = field(default_factory=lambda: deque(maxlen=300), repr=False)

    # -- persistence ------------------------------------------------------------

    PERSISTED = ("id", "url", "quality", "audio", "items", "noplaylist", "start", "end", "force",
                 "kind", "title", "output_dir", "status", "detail", "completed", "files",
                 "total_size", "added", "finished")

    def to_record(self) -> dict:
        d = {k: getattr(self, k) for k in self.PERSISTED}
        d["log"] = list(self.log)
        return d

    @classmethod
    def from_record(cls, d: dict) -> "Job":
        job = cls(**{k: d.get(k, getattr(cls, k, None)) for k in cls.PERSISTED if k in d or k == "id" or k == "url"})
        job.log = deque(d.get("log") or [], maxlen=300)
        if job.status in (INSPECTING, DOWNLOADING):
            job.status = INTERRUPTED
            job.detail = "The console was closed while this was downloading."
        if job.status in TERMINAL:
            job.percent = 100.0 if job.status != INTERRUPTED else None
        return job

    # -- files ------------------------------------------------------------------

    def set_files(self, paths: list[str]):
        """Record finished files with their sizes (skips anything that vanished)."""
        self.files, self.total_size = [], 0
        for path in paths:
            p = Path(path)
            if not p.is_file():
                continue
            size = p.stat().st_size
            self.total_size += size
            self.files.append({
                "index": len(self.files), "name": p.name, "path": str(p),
                "size": size, "size_text": human_size(size),
                "playable": p.suffix.lower() in PLAYABLE, "exists": True,
            })

    def refresh_files(self) -> bool:
        """Re-check that recorded files still exist. Returns True if anything changed."""
        changed = False
        for f in self.files:
            exists = Path(f["path"]).is_file()
            if exists != f.get("exists", True):
                f["exists"] = exists
                changed = True
        return changed

    @property
    def missing_files(self) -> int:
        return sum(1 for f in self.files if not f.get("exists", True))

    # -- view -------------------------------------------------------------------

    def to_dict(self) -> dict:
        d = asdict(self)
        d["log"] = list(self.log)
        d["total_size_text"] = human_size(self.total_size) if self.total_size else ""
        d["quality_label"] = "MP3 audio" if self.audio else QUALITY_LABELS.get(self.quality, self.quality)
        d["clip_label"] = clip_label(self.start, self.end)
        d["missing_files"] = self.missing_files
        # A finished job can be fetched again when it failed, was cut short, or lost files.
        d["can_redownload"] = self.status in TERMINAL and (
            self.status not in ("SUCCESS", "SKIPPED") or self.missing_files > 0 or not self.files)
        return d


def clip_label(start, end) -> str:
    if start is None and end is None:
        return ""
    from yt_engine import format_timestamp
    lo = format_timestamp(start or 0).replace(".", ":")
    hi = format_timestamp(end).replace(".", ":") if end is not None else "end"
    return f"{lo} – {hi}"


class QueueWorker:
    """Owns the job list and a single background thread that drains it."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.jobs: list[Job] = []
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._current: Optional[Job] = None
        self._cancel_requested: set[int] = set()
        self._dirty = False
        self._last_files_check = 0.0
        self.update_info: Optional[dict] = None     # filled by _check_update in the background
        self._load_history()
        self._ids = itertools.count(max((j.id for j in self.jobs), default=0) + 1)
        self.downloader = Downloader(settings, on_message=self._on_message, on_progress=self._on_progress)
        self._thread = threading.Thread(target=self._run, name="download-worker", daemon=True)
        self._thread.start()
        threading.Thread(target=self._check_update, name="update-check", daemon=True).start()

    def _check_update(self):
        try:
            self.update_info = check_for_update().to_dict()
        except Exception as e:  # never let the check disturb the app
            self.update_info = {"error": str(e), "available": False}

    # -- persistence ------------------------------------------------------------

    def _load_history(self):
        if not HISTORY_FILE.is_file():
            return
        try:
            records = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"Warning: could not read {HISTORY_FILE.name}: {e}")
            return
        for rec in records[-HISTORY_LIMIT:]:
            try:
                job = Job.from_record(rec)
                job.refresh_files()
                self.jobs.append(job)
            except Exception as e:  # a corrupt entry should not sink the whole history
                print(f"Warning: skipping unreadable history entry: {e}")
        if any(j.status == INTERRUPTED for j in self.jobs):
            self._dirty = True

    def save(self):
        """Write history to disk (atomically). Called after every state change."""
        with self._lock:
            records = [j.to_record() for j in self.jobs[-HISTORY_LIMIT:]]
            self._dirty = False
        tmp = HISTORY_FILE.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(records, ensure_ascii=False, indent=0), encoding="utf-8")
            tmp.replace(HISTORY_FILE)
        except OSError as e:
            print(f"Warning: could not write {HISTORY_FILE.name}: {e}")

    def set_output_dir(self, path: str) -> Path:
        """Change the download folder for future jobs and remember it across restarts."""
        folder = Path(path).expanduser()
        if not folder.is_absolute():
            folder = (BASE_DIR / folder).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write-test"
        probe.touch()
        probe.unlink()
        self.settings.output_dir = folder
        save_settings({"output_dir": str(folder)})
        return folder

    # -- called from Flask request threads --------------------------------------

    def add(self, **kwargs) -> Job:
        job = Job(id=next(self._ids), **kwargs)
        with self._lock:
            self.jobs.append(job)
        self._wake.set()
        self.save()
        return job

    def cancel(self, job_id: int) -> str:
        """Cancel a queued or running job. Returns 'queued', 'running' or ''."""
        with self._lock:
            for job in self.jobs:
                if job.id != job_id:
                    continue
                if job.status == QUEUED:
                    job.status, job.detail = "CANCELLED", "Removed before it started"
                    job.finished = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self.save()
                    return "queued"
                if job.status in (INSPECTING, DOWNLOADING):
                    self._cancel_requested.add(job_id)
                    self.downloader.cancel()
                    job.detail = "Cancelling..."
                    return "running"
        return ""

    def redownload(self, job_id: int) -> Optional[Job]:
        """Queue a fresh copy of a finished job (same URL and options)."""
        with self._lock:
            src = next((j for j in self.jobs if j.id == job_id), None)
        if src is None or src.status not in TERMINAL:
            return None
        return self.add(url=src.url, quality=src.quality, audio=src.audio, items=src.items,
                        noplaylist=src.noplaylist, start=src.start, end=src.end,
                        kind=src.kind, title=src.title, force=True)

    def clear_finished(self) -> int:
        with self._lock:
            before = len(self.jobs)
            self.jobs = [j for j in self.jobs if j.status not in TERMINAL]
            removed = before - len(self.jobs)
        if removed:
            self.save()
        return removed

    def snapshot(self) -> list[dict]:
        with self._lock:
            # Re-check file existence every 10 s so deleted files show up as missing.
            now = time.time()
            if now - self._last_files_check > 10:
                self._last_files_check = now
                if any(j.refresh_files() for j in self.jobs if j.status in TERMINAL):
                    self._dirty = True
            snap = [j.to_dict() for j in self.jobs]
            dirty = self._dirty
        if dirty:
            self.save()
        return snap

    def find(self, job_id: int) -> Optional[Job]:
        with self._lock:
            return next((j for j in self.jobs if j.id == job_id), None)

    # -- engine callbacks (worker thread) -----------------------------------------

    def _on_message(self, msg: str):
        job = self._current
        if job is not None:
            job.log.append(msg)

    def _on_progress(self, p: Progress):
        job = self._current
        if job is None:
            return
        where = f"{p.item_index}/{p.item_count}  " if p.item_index and p.item_count else ""
        if p.status == "downloading":
            job.percent, job.speed, job.eta = p.percent, p.speed, p.eta
            job.current = f"{where}{p.item_title or p.filename}"
        elif p.status == "finished":
            job.percent, job.speed, job.eta = 100.0, "", ""
        elif p.status == "postprocessing":
            job.current = f"{where}{p.item_title}  ({p.filename})".strip()

    # -- worker loop --------------------------------------------------------------

    def _next(self) -> Optional[Job]:
        with self._lock:
            for job in self.jobs:
                if job.status == QUEUED:
                    return job
        return None

    def _run(self):
        while True:
            job = self._next()
            if job is None:
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                continue
            self._current = job
            job.output_dir = str(self.settings.output_dir.resolve())
            try:
                if job.kind is None or not job.title:
                    job.status = INSPECTING
                    self.save()
                    info = self.downloader.inspect(job.url, noplaylist=job.noplaylist)
                    job.kind, job.title = info.kind, info.title
                if job.id in self._cancel_requested:
                    raise _Cancelled()
                job.status = DOWNLOADING
                self.save()
                result = self.downloader.download(
                    job.url, kind=job.kind, title=job.title, quality=job.quality,
                    audio=job.audio, items=job.items, noplaylist=job.noplaylist,
                    start=job.start, end=job.end, force=job.force)
                job.status, job.detail, job.completed = result.status, result.detail, result.completed
                job.set_files(result.files)
            except _Cancelled:
                job.status, job.detail = "CANCELLED", "Cancelled by user"
            except EngineError as e:
                job.status, job.detail = "FAILED", str(e)
            except Exception as e:  # keep the worker alive no matter what
                job.status, job.detail = "FAILED", f"{type(e).__name__}: {e}"
            finally:
                job.speed = job.eta = ""
                job.finished = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if job.status in TERMINAL and job.percent is not None and job.status != "CANCELLED":
                    job.percent = 100.0
                self._cancel_requested.discard(job.id)
                self._current = None
                self.save()


class _Cancelled(Exception):
    pass


def load_settings() -> dict:
    if SETTINGS_FILE.is_file():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def save_settings(values: dict):
    data = load_settings()
    data.update(values)
    try:
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"Warning: could not write {SETTINGS_FILE.name}: {e}")


worker: QueueWorker  # created in main()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _bad(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def api_state():
    s = worker.settings
    ff = ensure_ffmpeg(fetch=False)
    return jsonify({
        "jobs": worker.snapshot(),
        "settings": {
            "output_dir": str(s.output_dir.resolve()),
            "default_output_dir": str((BASE_DIR / "downloads").resolve()),
            "ffmpeg": s.ffmpeg,
            "ffmpeg_source": ff.source,
            "ffmpeg_version": ff.version,
            "ffmpeg_detail": ff.detail,
            "ffmpeg_fix": ff.fix,
            "ytdlp_version": ytdlp_version(),
            "app_version": current_version(),
            "update": worker.update_info,
            "cookies": s.cookies_from_browser or (str(s.cookies_file) if s.cookies_file else ""),
            "qualities": [{"value": q, "label": QUALITY_LABELS[q]} for q in QUALITIES],
        },
    })


@app.post("/api/inspect")
def api_inspect():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not is_youtube_url(url):
        return _bad("Please enter a valid YouTube URL.")
    try:
        info = worker.downloader.inspect(url, noplaylist=bool(data.get("noplaylist")))
    except EngineError as e:
        return _bad(str(e), 422)
    return jsonify(info.to_dict())


@app.post("/api/jobs")
def api_add_jobs():
    """
    Body: {"urls": [...] | "url": "...", "quality": "1080", "audio": false,
           "items": "", "noplaylist": false, "kind": "video"|"playlist"|null,
           "title": "", "total": <entry count for validating items>}
    """
    data = request.get_json(silent=True) or {}
    urls = data.get("urls") or ([data["url"]] if data.get("url") else [])
    urls = [u.strip() for u in urls if u and u.strip()]
    if not urls:
        return _bad("No URL given.")
    quality = normalize_quality(data.get("quality", "best"))
    if quality is None:
        return _bad("Invalid quality.")

    items = (data.get("items") or "").strip()
    if items and data.get("total"):
        items, warnings = parse_selection(items, int(data["total"]))
        if items is None:
            return _bad("Selection contains no valid entries. " + " ".join(warnings))

    start = end = None
    if (data.get("start") or "").strip() or (data.get("end") or "").strip():
        if data.get("kind") == "playlist":
            return _bad("Clip start/end only apply to single videos.")
        if not worker.settings.ffmpeg:
            return _bad("Clip download requires FFmpeg.")
        start = parse_timestamp(data.get("start")) if (data.get("start") or "").strip() else None
        end = parse_timestamp(data.get("end")) if (data.get("end") or "").strip() else None
        if (data.get("start") or "").strip() and start is None:
            return _bad("Clip start is not a valid time. Use mm:ss or h:mm:ss.")
        if (data.get("end") or "").strip() and end is None:
            return _bad("Clip end is not a valid time. Use mm:ss or h:mm:ss.")
        if start is not None and end is not None and end <= start:
            return _bad("Clip end must be after clip start.")

    added, skipped = [], []
    for url in urls:
        if not is_youtube_url(url):
            skipped.append(url)
            continue
        job = worker.add(
            url=url, quality=quality, audio=bool(data.get("audio")), items=items,
            noplaylist=bool(data.get("noplaylist")), start=start, end=end,
            kind=data.get("kind") if len(urls) == 1 else None,
            title=(data.get("title") or "") if len(urls) == 1 else "",
        )
        added.append(job.to_dict())
    return jsonify({"added": added, "skipped": skipped})


def _job_file(job_id: int, index: int) -> Path:
    """Resolve a (job, file index) pair to a path, refusing anything outside the job's download folder."""
    job = worker.find(job_id)
    if job is None or index < 0 or index >= len(job.files):
        abort(404)
    path = Path(job.files[index]["path"]).resolve()
    root = Path(job.output_dir or worker.settings.output_dir).resolve()
    if root not in path.parents or not path.is_file():
        abort(404)
    return path


@app.get("/api/jobs/<int:job_id>/files/<int:index>")
def api_stream_file(job_id: int, index: int):
    """Stream a finished file to the in-page player (supports seeking via Range requests)."""
    path = _job_file(job_id, index)
    mimetype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return send_file(path, mimetype=mimetype, conditional=True)


@app.post("/api/jobs/<int:job_id>/files/<int:index>/open")
def api_open_file(job_id: int, index: int):
    """Open a finished file with the default application on this computer."""
    path = _job_file(job_id, index)
    try:
        if platform.system() == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        return _bad(f"Could not open file: {e}", 500)
    return jsonify({"ok": True})


@app.post("/api/jobs/<int:job_id>/reveal")
def api_reveal_job(job_id: int):
    """Open the folder containing the job's files, highlighting the first one where the OS allows."""
    path = _job_file(job_id, 0)
    try:
        if platform.system() == "Windows":
            # /select, highlights the file inside its folder.
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except Exception as e:
        return _bad(f"Could not open folder: {e}", 500)
    return jsonify({"ok": True, "folder": str(path.parent)})


@app.delete("/api/jobs/<int:job_id>")
def api_remove_job(job_id: int):
    """Remove a queued job, or cancel one that is running."""
    what = worker.cancel(job_id)
    if what:
        return jsonify({"ok": True, "cancelled": what})
    return _bad("This job is not queued or running.", 409)


@app.post("/api/jobs/<int:job_id>/redownload")
def api_redownload(job_id: int):
    job = worker.redownload(job_id)
    if job is None:
        return _bad("Only finished jobs can be downloaded again.", 409)
    return jsonify(job.to_dict())


@app.post("/api/settings")
def api_settings():
    """Change the download folder. Applies to jobs that start after this call."""
    data = request.get_json(silent=True) or {}
    path = (data.get("output_dir") or "").strip()
    if not path:
        return _bad("No folder given.")
    try:
        folder = worker.set_output_dir(path)
    except OSError as e:
        return _bad(f"Cannot use that folder: {e}", 422)
    return jsonify({"ok": True, "output_dir": str(folder)})


@app.post("/api/browse-folder")
def api_browse_folder():
    """
    Open the operating system's folder picker on this computer (the browser
    runs on the same machine). Falls back with an error if no desktop is available.
    """
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(initialdir=str(worker.settings.output_dir), title="Choose download folder")
        root.destroy()
    except Exception as e:
        return _bad(f"Folder picker unavailable ({type(e).__name__}); type the path instead.", 501)
    return jsonify({"output_dir": chosen or ""})


@app.post("/api/jobs/clear")
def api_clear_jobs():
    return jsonify({"removed": worker.clear_finished()})


@app.post("/api/update")
def api_update():
    ok, output = update_ytdlp()
    return jsonify({"ok": ok, "output": output[-4000:],
                    "note": "Restart the console (close this window and run Start.bat) to load the new version."})


@app.post("/api/update-app")
def api_update_app():
    """Pull the latest application code from GitHub. Files are swapped on disk; restart to load them."""
    lines: list[str] = []
    result = update_app(lines.append)
    if result.ok:
        worker.update_info = {"available": False, "local": current_version(), "remote": current_version()}
    return jsonify({**result.to_dict(), "log": lines,
                    "note": "Close this window and run Start.bat again to load the new version."
                            if result.changed else ""})


@app.post("/api/open-folder")
def api_open_folder():
    folder = worker.settings.output_dir.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if platform.system() == "Windows":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception as e:
        return _bad(f"Could not open folder: {e}", 500)
    return jsonify({"ok": True, "path": str(folder)})


@app.get("/api/log")
def api_log():
    path = worker.settings.log_file
    if not path.is_file():
        return jsonify({"lines": []})
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()[-200:]
    return jsonify({"lines": lines})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="yt_web.py", description="Local web console for the YouTube downloader.")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--output", default=None, help="Download folder (default: last used, else ./downloads)")
    p.add_argument("--cookies-from-browser", metavar="BROWSER")
    p.add_argument("--cookies-file", metavar="PATH")
    p.add_argument("--no-ffmpeg", action="store_true")
    p.add_argument("--no-browser", action="store_true", help="Do not open a browser window")
    return p


def main():
    global worker
    args = build_arg_parser().parse_args()
    saved = load_settings()
    output = args.output or saved.get("output_dir") or str(BASE_DIR / "downloads")
    settings = Settings(
        output_dir=Path(output),
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=Path(args.cookies_file) if args.cookies_file else None,
        use_ffmpeg=not args.no_ffmpeg,
    )
    settings.output_dir.mkdir(parents=True, exist_ok=True)

    ff = ensure_ffmpeg(fetch=not args.no_ffmpeg, on_message=print)
    worker = QueueWorker(settings)

    url = f"http://127.0.0.1:{args.port}/"
    print(f"YouTube Downloader web console  |  yt-dlp {ytdlp_version()}")
    print(f"Downloads : {settings.output_dir.resolve()}")
    if ff.available:
        print(f"FFmpeg    : {ff.source} {ff.version} ({ff.location or ff.detail.split(';')[0]})")
        if ";" in ff.detail:
            print(f"            note: {ff.detail.split(';', 1)[1].strip()}")
    else:
        print(f"FFmpeg    : NOT AVAILABLE - {ff.detail}")
        print("            Video and MP3 downloads will fail until this is fixed. How to fix:")
        for i, step in enumerate(ff.fix, 1):
            print(f"            {i}. {step}")
        print("            See TROUBLESHOOTING.md for details.")
    print(f"Open      : {url}   (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
