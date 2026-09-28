#!/usr/bin/env python3
"""
yt_update.py - update this application from GitHub.

    python yt_update.py            update if a newer version exists
    python yt_update.py --check    only report whether an update exists

Two strategies, chosen automatically:
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
    dirty = _run(["git", "status", "--porcelain", "--untracked-files=no"]).stdout.strip()
    if dirty:
        return UpdateResult(False, False,
                            "Local files have been modified; refusing to overwrite them.\n"
                            "Run  git stash  (or discard the changes) and try again.",
                            output=dirty)
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
    if result.changed:
        say(result.message)
        say("Restart the console (close the window and run Start.bat) to use the new version.")
    else:
        say(result.message)
    return result


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="Update this application from GitHub.")
    p.add_argument("--check", action="store_true", help="Only check whether an update is available")
    args = p.parse_args()

    if args.check:
        info = check_for_update()
        if info.error:
            print(f"Could not check for updates: {info.error}")
            return 1
        print(f"Installed: {info.local or 'unknown'}   Latest: {info.remote}   "
              f"{'UPDATE AVAILABLE' if info.available else 'up to date'}   ({info.strategy})")
        return 0

    result = update_app(print)
    if result.output:
        print(result.output)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
