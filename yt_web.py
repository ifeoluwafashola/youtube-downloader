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
import os
import platform
import subprocess
import threading
import webbrowser
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from flask import Flask, jsonify, render_template, request
except ImportError:  # pragma: no cover
    raise SystemExit("Flask is not installed. Run:  pip install -r requirements.txt")

from yt_engine import (
    QUALITIES, QUALITY_LABELS,
    Downloader, EngineError, Progress, Settings,
    ensure_ffmpeg, is_youtube_url, normalize_quality, parse_selection,
    update_ytdlp, ytdlp_version,
)

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))


# ---------------------------------------------------------------------------
# Queue model
# ---------------------------------------------------------------------------

QUEUED, INSPECTING, DOWNLOADING = "QUEUED", "INSPECTING", "DOWNLOADING"
TERMINAL = {"SUCCESS", "PARTIAL", "FAILED", "SKIPPED", "CANCELLED"}


@dataclass
class Job:
    id: int
    url: str
    quality: str = "best"
    audio: bool = False
    items: str = ""
    noplaylist: bool = False
    kind: Optional[str] = None       # filled by inspect if not supplied
    title: str = ""
    status: str = QUEUED
    percent: Optional[float] = None
    speed: str = ""
    eta: str = ""
    current: str = ""                # "3/12  Some title" or post-processor name
    detail: str = ""
    completed: int = 0
    added: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    log: deque = field(default_factory=lambda: deque(maxlen=40), repr=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["log"] = list(self.log)
        d["quality_label"] = "MP3 audio" if self.audio else QUALITY_LABELS.get(self.quality, self.quality)
        return d


class QueueWorker:
    """Owns the job list and a single background thread that drains it."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.jobs: list[Job] = []
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._current: Optional[Job] = None
        self.downloader = Downloader(settings, on_message=self._on_message, on_progress=self._on_progress)
        self._thread = threading.Thread(target=self._run, name="download-worker", daemon=True)
        self._thread.start()

    # -- called from Flask request threads --------------------------------------

    def add(self, **kwargs) -> Job:
        job = Job(id=next(self._ids), **kwargs)
        with self._lock:
            self.jobs.append(job)
        self._wake.set()
        return job

    def remove(self, job_id: int) -> bool:
        with self._lock:
            for job in self.jobs:
                if job.id == job_id and job.status == QUEUED:
                    job.status = "CANCELLED"
                    return True
        return False

    def clear_finished(self) -> int:
        with self._lock:
            before = len(self.jobs)
            self.jobs = [j for j in self.jobs if j.status not in TERMINAL]
            return before - len(self.jobs)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [j.to_dict() for j in self.jobs]

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
            try:
                if job.kind is None or not job.title:
                    job.status = INSPECTING
                    info = self.downloader.inspect(job.url, noplaylist=job.noplaylist)
                    job.kind, job.title = info.kind, info.title
                job.status = DOWNLOADING
                result = self.downloader.download(
                    job.url, kind=job.kind, title=job.title, quality=job.quality,
                    audio=job.audio, items=job.items, noplaylist=job.noplaylist)
                job.status, job.detail, job.completed = result.status, result.detail, result.completed
            except EngineError as e:
                job.status, job.detail = "FAILED", str(e)
            except Exception as e:  # keep the worker alive no matter what
                job.status, job.detail = "FAILED", f"{type(e).__name__}: {e}"
            finally:
                job.speed = job.eta = ""
                if job.status in TERMINAL and job.percent is not None:
                    job.percent = 100.0
                self._current = None


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
            "ffmpeg": s.ffmpeg,
            "ffmpeg_source": ff.source,
            "ffmpeg_version": ff.version,
            "ffmpeg_detail": ff.detail,
            "ffmpeg_fix": ff.fix,
            "ytdlp_version": ytdlp_version(),
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

    added, skipped = [], []
    for url in urls:
        if not is_youtube_url(url):
            skipped.append(url)
            continue
        job = worker.add(
            url=url, quality=quality, audio=bool(data.get("audio")), items=items,
            noplaylist=bool(data.get("noplaylist")),
            kind=data.get("kind") if len(urls) == 1 else None,
            title=(data.get("title") or "") if len(urls) == 1 else "",
        )
        added.append(job.to_dict())
    return jsonify({"added": added, "skipped": skipped})


@app.delete("/api/jobs/<int:job_id>")
def api_remove_job(job_id: int):
    if worker.remove(job_id):
        return jsonify({"ok": True})
    return _bad("Only queued jobs can be removed.", 409)


@app.post("/api/jobs/clear")
def api_clear_jobs():
    return jsonify({"removed": worker.clear_finished()})


@app.post("/api/update")
def api_update():
    ok, output = update_ytdlp()
    return jsonify({"ok": ok, "output": output[-4000:],
                    "note": "Restart the console (close this window and run Start.bat) to load the new version."})


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
    p.add_argument("--output", default=str(BASE_DIR / "downloads"), help="Download folder")
    p.add_argument("--cookies-from-browser", metavar="BROWSER")
    p.add_argument("--cookies-file", metavar="PATH")
    p.add_argument("--no-ffmpeg", action="store_true")
    p.add_argument("--no-browser", action="store_true", help="Do not open a browser window")
    return p


def main():
    global worker
    args = build_arg_parser().parse_args()
    settings = Settings(
        output_dir=Path(args.output),
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
