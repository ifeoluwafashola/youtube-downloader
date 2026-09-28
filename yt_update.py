#!/usr/bin/env python3
"""
yt_update.py - one-step update: this application (from GitHub) and yt-dlp (from PyPI).

    python yt_update.py            update both if newer versions exist
    python yt_update.py --check    only report what is available

There is deliberately a single "update" for the user. Two things move
underneath it - the program code and the yt-dlp library that talks to
YouTube - but the user never needs to know which one fixed their problem.

Application update: two strategies, chosen automatically:
  * git   - the folder is a git clone and git is installed: fast-forward pull.
  * zip   - otherwise: download the repository zip from GitHub and copy the
            files over this folder. User data (.venv, downloads, bin, .git)
            is never touched.

If requirements.txt changed, dependencies are reinstalled into the current
environment. A restart of the console is needed afterwards either way.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Optional

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_REPO = "ifeoluwafashola/youtube-downloader"
BRANCH = "main"
# Folders that belong to the user, not the application. Never overwritten or deleted.
PRESERVE = {".venv", "downloads", "bin", ".git", "__pycache__", ".pytest_cache"}
VERSION_FILE = BASE_DIR / ".app_version"     # zip strategy: sha of the installed commit
USER_AGENT = "youtube-downloader-updater"


@dataclass
class UpdateInfo:
    strategy: str                 # "git" | "zip"
    repo: str
    local: str = ""               # short sha (or "" if unknown)
    remote: str = ""
    available: bool = False
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class UpdateResult:
    ok: bool
    changed: bool
    message: str
    files: list[str] = field(default_factory=list)
    requirements_changed: bool = False
    output: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class YtdlpInfo:
    installed: str = ""
    latest: str = ""
    available: bool = False
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CombinedInfo:
    """Everything the startup check learns, for one banner."""
    app: UpdateInfo
    ytdlp: YtdlpInfo

    @property
    def available(self) -> bool:
        return self.app.available or self.ytdlp.available

    def to_dict(self) -> dict:
        return {"available": self.available, "app": self.app.to_dict(), "ytdlp": self.ytdlp.to_dict()}


@dataclass
class CombinedResult:
    app: UpdateResult
    ytdlp_ok: bool = True
    ytdlp_before: str = ""
    ytdlp_after: str = ""
    ytdlp_output: str = ""

    @property
    def ok(self) -> bool:
        return self.app.ok and self.ytdlp_ok

    @property
    def changed(self) -> bool:
        return self.app.changed or (self.ytdlp_before != self.ytdlp_after and bool(self.ytdlp_after))

    @property
    def message(self) -> str:
        parts = [self.app.message]
        if not self.ytdlp_ok:
            parts.append("yt-dlp upgrade failed.")
        elif self.ytdlp_before != self.ytdlp_after and self.ytdlp_after:
            parts.append(f"yt-dlp {self.ytdlp_before} -> {self.ytdlp_after}.")
        else:
            parts.append(f"yt-dlp {self.ytdlp_after or self.ytdlp_before} is current.")
        return " ".join(parts)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "changed": self.changed, "message": self.message,
                "app": self.app.to_dict(),
                "ytdlp": {"ok": self.ytdlp_ok, "before": self.ytdlp_before, "after": self.ytdlp_after,
                          "output": self.ytdlp_output}}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], cwd: Path = BASE_DIR, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)


def _git_available() -> bool:
    return (BASE_DIR / ".git").is_dir() and shutil.which("git") is not None


def _repo_slug() -> str:
    """owner/repo, from the git remote if possible, else the built-in default."""
    if _git_available():
        proc = _run(["git", "remote", "get-url", "origin"])
        url = proc.stdout.strip()
        if proc.returncode == 0 and "github.com" in url:
            slug = url.split("github.com")[-1].lstrip(":/").removesuffix(".git")
            if slug.count("/") == 1:
                return slug
    return DEFAULT_REPO


def _http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def _http_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_version() -> str:
    """Short identifier of the installed version, for display."""
    if _git_available():
        proc = _run(["git", "rev-parse", "--short", "HEAD"])
        if proc.returncode == 0:
            return proc.stdout.strip()
    if VERSION_FILE.is_file():
        return VERSION_FILE.read_text().strip()[:7]
    return "unknown"


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def check_for_update() -> UpdateInfo:
    """Compare the installed commit with the tip of the GitHub branch. Network access required."""
    repo = _repo_slug()
    try:
        if _git_available():
            info = UpdateInfo("git", repo)
            fetch = _run(["git", "fetch", "--quiet", "origin", BRANCH])
            if fetch.returncode != 0:
                info.error = fetch.stderr.strip() or "git fetch failed"
                return info
            info.local = _run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
            info.remote = _run(["git", "rev-parse", "--short", f"origin/{BRANCH}"]).stdout.strip()
            behind = _run(["git", "rev-list", "--count", f"HEAD..origin/{BRANCH}"]).stdout.strip()
            info.available = behind.isdigit() and int(behind) > 0
            return info

        info = UpdateInfo("zip", repo)
        data = _http_json(f"https://api.github.com/repos/{repo}/commits/{BRANCH}")
        info.remote = data["sha"][:7]
        info.local = VERSION_FILE.read_text().strip()[:7] if VERSION_FILE.is_file() else ""
        info.available = info.local != info.remote
        return info
    except Exception as e:
        return UpdateInfo("git" if _git_available() else "zip", repo, error=f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

def _update_git(say: Callable[[str], None]) -> UpdateResult:
    dirty = _run(["git", "status", "--porcelain", "--untracked-files=no"]).stdout
    if dirty.strip():
        # Files that differ only in CRLF/LF (e.g. after a .gitattributes change)
        # are not real edits: reset them so the pull can proceed.
        real = _run(["git", "diff", "--quiet", "--ignore-cr-at-eol", "HEAD", "--"]).returncode != 0
        if real:
            return UpdateResult(False, False,
                                "Local files have been modified; refusing to overwrite them.\n"
                                "Run  git stash  (or discard the changes) and try again.",
                                output=dirty.strip())
        # Porcelain format: two status columns, a space, then the path.
        files = [line[3:] for line in dirty.splitlines() if len(line) > 3]
        say(f"Resetting line endings on: {', '.join(files)}")
        _run(["git", "checkout", "--", *files])
    before = _run(["git", "rev-parse", "HEAD"]).stdout.strip()
    say("Fetching latest version from GitHub...")
    pull = _run(["git", "pull", "--ff-only", "--quiet", "origin", BRANCH], timeout=300)
    if pull.returncode != 0:
        return UpdateResult(False, False, "git pull failed.", output=pull.stderr.strip())
    after = _run(["git", "rev-parse", "HEAD"]).stdout.strip()
    if before == after:
        return UpdateResult(True, False, f"Already up to date ({after[:7]}).")
    files = _run(["git", "diff", "--name-only", before, after]).stdout.split()
    log = _run(["git", "log", "--oneline", f"{before}..{after}"]).stdout.strip()
    return UpdateResult(True, True, f"Updated {before[:7]} -> {after[:7]}.", files=files,
                        requirements_changed="requirements.txt" in files, output=log)


def _update_zip(say: Callable[[str], None]) -> UpdateResult:
    repo = _repo_slug()
    say("Checking GitHub for the latest version...")
    data = _http_json(f"https://api.github.com/repos/{repo}/commits/{BRANCH}")
    remote_sha = data["sha"]
    local_sha = VERSION_FILE.read_text().strip() if VERSION_FILE.is_file() else ""
    if local_sha == remote_sha:
        return UpdateResult(True, False, f"Already up to date ({remote_sha[:7]}).")

    say("Downloading...")
    blob = _http_bytes(f"https://github.com/{repo}/archive/{remote_sha}.zip")
    changed: list[str] = []
    with zipfile.ZipFile(io.BytesIO(blob)) as zf, tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        zf.extractall(tmp_path)
        roots = [p for p in tmp_path.iterdir() if p.is_dir()]
        if len(roots) != 1:
            return UpdateResult(False, False, "Unexpected archive layout from GitHub.")
        src_root = roots[0]

        # Copy new/changed files over. Nothing in PRESERVE is touched.
        for src in src_root.rglob("*"):
            rel = src.relative_to(src_root)
            if rel.parts and rel.parts[0] in PRESERVE:
                continue
            dst = BASE_DIR / rel
            if src.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
                continue
            if dst.is_file() and _file_hash(dst) == _file_hash(src):
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            changed.append(rel.as_posix())

        # Files removed upstream are intentionally left in place: without a
        # manifest of what we installed, deleting is riskier than a stray file.

    VERSION_FILE.write_text(remote_sha + "\n")
    return UpdateResult(True, bool(changed), f"Updated to {remote_sha[:7]} ({len(changed)} file(s) changed).",
                        files=changed, requirements_changed="requirements.txt" in changed)


def _reinstall_requirements(say: Callable[[str], None]) -> str:
    say("requirements.txt changed - installing dependencies...")
    proc = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "-r",
                           str(BASE_DIR / "requirements.txt")], capture_output=True, text=True)
    # Keep Start.bat's stamp in sync so it does not reinstall again.
    stamp = Path(sys.prefix) / ".requirements.stamp"
    if proc.returncode == 0:
        try:
            shutil.copy2(BASE_DIR / "requirements.txt", stamp)
        except OSError:
            pass
    return (proc.stdout + proc.stderr).strip()


def update_app(on_message: Optional[Callable[[str], None]] = None) -> UpdateResult:
    """Update in place. Safe to call from the running console; a restart is needed afterwards."""
    say = on_message or (lambda _m: None)
    try:
        result = _update_git(say) if _git_available() else _update_zip(say)
    except Exception as e:
        return UpdateResult(False, False, f"Update failed: {type(e).__name__}: {e}")
    if result.ok and result.requirements_changed:
        result.output = (result.output + "\n" + _reinstall_requirements(say)).strip()
    say(result.message)
    return result


# ---------------------------------------------------------------------------
# yt-dlp
# ---------------------------------------------------------------------------

def installed_ytdlp_version() -> str:
    """Ask a fresh interpreter, so the answer is right even after an in-process upgrade."""
    proc = subprocess.run([sys.executable, "-c", "import yt_dlp.version as v; print(v.__version__)"],
                          capture_output=True, text=True, timeout=60)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _version_key(text: str) -> tuple:
    """'2026.08.19' and '2026.8.19' are the same release; compare numerically."""
    parts = []
    for piece in text.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def check_ytdlp() -> YtdlpInfo:
    info = YtdlpInfo(installed=installed_ytdlp_version())
    try:
        data = _http_json("https://pypi.org/pypi/yt-dlp/json")
        info.latest = data["info"]["version"]
        info.available = bool(info.installed) and _version_key(info.latest) > _version_key(info.installed)
    except Exception as e:
        info.error = f"{type(e).__name__}: {e}"
    return info


def update_ytdlp(say: Callable[[str], None]) -> tuple[bool, str, str, str]:
    """Upgrade yt-dlp in this environment. Returns (ok, before, after, pip output)."""
    before = installed_ytdlp_version()
    say("Checking for a newer yt-dlp...")
    proc = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "yt-dlp"],
                          capture_output=True, text=True, timeout=600)
    after = installed_ytdlp_version() if proc.returncode == 0 else before
    output = (proc.stdout + "\n" + proc.stderr).strip()
    if proc.returncode != 0:
        say("yt-dlp upgrade failed - see details below.")
    elif after != before:
        say(f"yt-dlp updated {before} -> {after}.")
    else:
        say(f"yt-dlp {after} is already current.")
    return proc.returncode == 0, before, after, output


# ---------------------------------------------------------------------------
# combined
# ---------------------------------------------------------------------------

def check_all() -> CombinedInfo:
    return CombinedInfo(app=check_for_update(), ytdlp=check_ytdlp())


def update_all(on_message: Optional[Callable[[str], None]] = None) -> CombinedResult:
    """The one update. Program first (it may change requirements), then yt-dlp."""
    say = on_message or (lambda _m: None)
    app = update_app(say)
    ok, before, after, output = update_ytdlp(say)
    result = CombinedResult(app=app, ytdlp_ok=ok, ytdlp_before=before, ytdlp_after=after, ytdlp_output=output)
    if result.changed:
        say("Restart the console (close the window and run Start.bat) to use the new version.")
    return result


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="Update this program and yt-dlp.")
    p.add_argument("--check", action="store_true", help="Only report whether updates are available")
    p.add_argument("--app-only", action="store_true", help="Update the program but not yt-dlp")
    args = p.parse_args()

    if args.check:
        info = check_all()
        a, y = info.app, info.ytdlp
        print(f"Program : installed {a.local or 'unknown'}, latest {a.remote or '?'}  "
              f"{'- UPDATE AVAILABLE' if a.available else '- up to date'}" + (f"  ({a.error})" if a.error else ""))
        print(f"yt-dlp  : installed {y.installed or '?'}, latest {y.latest or '?'}  "
              f"{'- UPDATE AVAILABLE' if y.available else '- up to date'}" + (f"  ({y.error})" if y.error else ""))
        return 0

    if args.app_only:
        result = update_app(print)
        if result.output:
            print(result.output)
        return 0 if result.ok else 1

    result = update_all(print)
    if result.app.output:
        print(result.app.output)
    if not result.ytdlp_ok and result.ytdlp_output:
        print(result.ytdlp_output)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
