#!/usr/bin/env python3
"""
YtUnified.py - command-line front end for yt_engine.

    python YtUnified.py                       interactive menu
    python YtUnified.py --url URL [options]   one download, then exit
    python YtUnified.py --list-formats URL    show available formats
    python YtUnified.py --update              upgrade yt-dlp

Exit codes: 0 success, 1 download/detection failure, 2 bad arguments.
For the browser-based console see yt_web.py / Start.bat.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from yt_engine import (
    AUDIO_FORMATS, DEFAULT_AUDIO, normalize_audio, CONTAINERS, DEFAULT_CONTAINER,
    QUALITIES, QUALITY_LABELS, QUALITY_MENU,
    Downloader, EngineError, MediaInfo, Progress, Settings,
    ensure_ffmpeg, is_video_in_playlist_url, is_youtube_url,
    normalize_quality, parse_selection, update_ytdlp, ytdlp_version,
)


# ---------------------------------------------------------------------------
# Terminal rendering of engine callbacks
# ---------------------------------------------------------------------------

def print_message(msg: str):
    print(msg)


def print_progress(p: Progress):
    prefix = f"[{p.item_index}/{p.item_count}] " if p.item_index and p.item_count else ""
    if p.status == "downloading":
        pct = f"{p.percent:5.1f}%" if p.percent is not None else "  ...  "
        line = f"\r  {prefix}{pct}  {p.speed:>12}  ETA {p.eta:>6}"
        print(line.ljust(70), end="", flush=True)
    elif p.status == "finished":
        print(f"\r  {prefix}Download finished, post-processing...".ljust(70))
    elif p.status == "postprocessing":
        print(f"  {prefix}{p.filename}...")


def make_downloader(settings: Settings) -> Downloader:
    return Downloader(settings, on_message=print_message, on_progress=print_progress)


def report(result):
    print()
    if result.status == "SUCCESS":
        print(f"Done. {result.completed} file(s) downloaded.")
    elif result.status == "PARTIAL":
        print(f"Finished with errors: {result.completed} succeeded, {result.failed} failed.")
    elif result.status == "SKIPPED":
        print(f"Skipped: {result.detail}")
    else:
        print(f"FAILED: {result.detail}")


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------

def prompt_quality() -> str | None:
    print("\nSelect quality:")
    for key, value in QUALITY_MENU.items():
        print(f"{key}. {QUALITY_LABELS[value]}")
    sel = input("Enter choice (0-5 or a resolution): ").strip()
    return normalize_quality(sel)


def prompt_cookies(settings: Settings):
    print("\nCookie source (for age-restricted or members-only videos):")
    print("1. None")
    print("2. From a browser (chrome, firefox, edge, brave, opera, vivaldi)")
    print("3. From a cookies.txt file")
    sel = input("Select option (1-3, default 1): ").strip()
    if sel == "2":
        browser = input("Browser name: ").strip().lower()
        if browser:
            settings.cookies_from_browser = browser
            print(f"Using cookies from {browser}.")
    elif sel == "3":
        path = Path(input("Path to cookies.txt: ").strip()).expanduser()
        if path.is_file():
            settings.cookies_file = path
            print(f"Using cookie file {path}.")
        else:
            print("File not found. Continuing without cookies.")
    else:
        print("Continuing without cookies.")


def prompt_playlist_scope(info: MediaInfo) -> str | None:
    """Return a playlist_items string ("" = all) or None to cancel."""
    if not info.entries:
        print("No entries found in this playlist.")
        return None
    print(f"\n{'#':>4}  Title")
    print("-" * 60)
    for e in info.entries:
        print(f"{e.index:>4}  {e.title}")
    print("-" * 60)

    print("\nWhich videos?")
    print("1. All")
    print("2. A range (e.g. 5-20)")
    print("3. Specific videos (e.g. 1,3,7 or 1 3 7)")
    sel = input("Select option (1-3): ").strip()
    if sel == "1":
        return ""
    if sel in ("2", "3"):
        raw = input("Enter selection: ").strip()
        items, warnings = parse_selection(raw, len(info.entries))
        for w in warnings:
            print(w)
        return items or None
    print("Invalid choice.")
    return None


def prompt_audio_format() -> str | None:
    codes = list(AUDIO_FORMATS)
    print("\nAudio format:")
    for i, code in enumerate(codes, 1):
        print(f"{i}. {AUDIO_FORMATS[code][0]}")
    sel = input(f"Enter choice (1-{len(codes)}, default 1): ").strip() or "1"
    if sel.isdigit() and 1 <= int(sel) <= len(codes):
        return codes[int(sel) - 1]
    return normalize_audio(sel)


def prompt_mode() -> tuple[str, str] | None:
    """Return (quality, audio_code_or_empty) or None if cancelled."""
    print("\nDownload Options:")
    print("1. Download video (best quality)")
    print("2. Download video (choose quality)")
    print("3. Download audio only (MP3 / WAV / original)")
    choice = input("\nSelect option (1-3): ").strip()
    if choice == "1":
        return "best", ""
    if choice == "2":
        q = prompt_quality()
        if q is None:
            print("Invalid choice! Pick 0-5 or a valid resolution.")
            return None
        return q, ""
    if choice == "3":
        a = prompt_audio_format()
        if a is None:
            print("Invalid audio format.")
            return None
        return "best", a
    print("Invalid option! Please choose 1-3.")
    return None


def interactive_main(settings: Settings):
    print("YouTube Downloader (Video + Playlist)")
    print("=" * 37)
    print(f"yt-dlp {ytdlp_version()}  |  output: {settings.output_dir.resolve()}")
    ff = ensure_ffmpeg(fetch=settings.use_ffmpeg, on_message=print)
    if ff.available:
        print(f"FFmpeg: {ff.source} {ff.version} - high quality downloads available")
    else:
        print(f"FFmpeg NOT available ({ff.detail}) - most downloads will fail. How to fix:")
        for i, step in enumerate(ff.fix, 1):
            print(f"  {i}. {step}")

    if not (settings.cookies_from_browser or settings.cookies_file):
        prompt_cookies(settings)
    dl = make_downloader(settings)

    while True:
        url = input("\nEnter YouTube video or playlist URL (or 'quit' to exit): ").strip()
        if url.lower() in ("quit", "exit", "q"):
            break
        if not is_youtube_url(url):
            print("Please enter a valid YouTube URL!")
            continue

        noplaylist = False
        if is_video_in_playlist_url(url):
            ans = input("This link has both a video and a playlist. Download (v)ideo only or whole (p)laylist? [v/p]: ")
            noplaylist = ans.strip().lower() != "p"

        print("\nInspecting URL...")
        try:
            info = dl.inspect(url, noplaylist=noplaylist)
        except EngineError as e:
            print(f"Could not inspect URL: {e}")
            continue

        if info.kind == "playlist":
            print(f"\nDetected: playlist\nPlaylist : {info.title}\nVideos   : {info.count}")
        else:
            print(f"\nDetected: single video\nTitle    : {info.title}\nUploader : {info.uploader}")
            if info.duration_text:
                print(f"Duration : {info.duration_text}")

        mode = prompt_mode()
        if mode is None:
            continue
        quality, audio = mode

        items = ""
        if info.kind == "playlist":
            items = prompt_playlist_scope(info)
            if items is None:
                print("No valid selection. Cancelled.")
                continue

        what = AUDIO_FORMATS[audio][0] if audio else QUALITY_LABELS[quality]
        scope = "" if info.kind == "video" else (" (all videos)" if items == "" else f" (items {items})")
        print(f"\nDownloading {what}{scope}...")
        result = dl.download(url, kind=info.kind, title=info.title, quality=quality,
                             audio=audio or None, items=items, noplaylist=noplaylist)
        report(result)

        if input("\nDownload another? (y/n): ").strip().lower() not in ("y", "yes"):
            break
    print("Goodbye!")


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="YtUnified.py",
        description="Download a YouTube video or playlist. Run with no --url for interactive mode.",
    )
    p.add_argument("--url", help="YouTube video or playlist URL")
    p.add_argument("--quality", default="best",
                   help=f"Max resolution: {', '.join(QUALITIES)} (default best)")
    p.add_argument("--audio", nargs="?", const=DEFAULT_AUDIO, metavar="FORMAT",
                   help="Audio only. FORMAT: " + ", ".join(AUDIO_FORMATS) + f" (default {DEFAULT_AUDIO})")
    p.add_argument("--container", default=DEFAULT_CONTAINER, choices=list(CONTAINERS),
                   help=f"Video container (default {DEFAULT_CONTAINER})")
    p.add_argument("--output", default="./downloads", help="Output directory (default ./downloads)")
    p.add_argument("--items", default="",
                   help="Playlist selection, e.g. '5-20' or '1,3,7' (playlists only; default all)")
    p.add_argument("--no-playlist", action="store_true",
                   help="For watch?v=..&list=.. links, download only the video")
    p.add_argument("--no-ffmpeg", action="store_true",
                   help="Force single-file formats even if FFmpeg is present")
    p.add_argument("--cookies-from-browser", metavar="BROWSER",
                   help="Load cookies from a browser, e.g. chrome, firefox, edge")
    p.add_argument("--cookies-file", metavar="PATH", help="Path to a cookies.txt file")
    p.add_argument("--list-formats", metavar="URL", help="List available formats for URL and exit")
    p.add_argument("--update", action="store_true", help="Upgrade yt-dlp and exit")
    p.add_argument("--version", action="version", version=f"%(prog)s (yt-dlp {ytdlp_version()})")
    return p


def settings_from_args(args) -> Settings:
    return Settings(
        output_dir=Path(args.output),
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=Path(args.cookies_file) if args.cookies_file else None,
        use_ffmpeg=not args.no_ffmpeg,
    )


def run_noninteractive(args, settings: Settings) -> int:
    if not is_youtube_url(args.url):
        print("Error: --url must be a YouTube URL.")
        return 2
    quality = normalize_quality(args.quality)
    if quality is None:
        print(f"Error: --quality must be one of {', '.join(QUALITIES)}.")
        return 2
    audio = None
    if args.audio:
        audio = normalize_audio(args.audio)
        if audio is None:
            print(f"Error: --audio must be one of {', '.join(AUDIO_FORMATS)}.")
            return 2
    if args.cookies_file and not settings.cookies_file.is_file():
        print(f"Warning: cookie file not found: {args.cookies_file}")

    ensure_ffmpeg(fetch=settings.use_ffmpeg, on_message=print)
    dl = make_downloader(settings)
    print("Inspecting URL...")
    try:
        info = dl.inspect(args.url, noplaylist=args.no_playlist)
    except EngineError as e:
        print(f"Error: could not determine URL type: {e}")
        return 1
    print(f"{info.kind}: {info.title}")

    result = dl.download(args.url, kind=info.kind, title=info.title, quality=quality,
                         audio=audio, items=args.items, noplaylist=args.no_playlist,
                         container=args.container)
    report(result)
    return 0 if result.ok or result.status == "SKIPPED" else 1


def main() -> int:
    args = build_arg_parser().parse_args()
    settings = settings_from_args(args)

    if args.update:
        print("Upgrading yt-dlp...")
        ok, out = update_ytdlp()
        print(out)
        return 0 if ok else 1

    if args.list_formats:
        try:
            print(make_downloader(settings).list_formats(args.list_formats))
            return 0
        except EngineError as e:
            print(f"Error: {e}")
            return 1

    if args.url:
        return run_noninteractive(args, settings)

    interactive_main(settings)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
