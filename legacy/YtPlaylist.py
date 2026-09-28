#!/usr/bin/env python3
"""
YouTube Playlist Downloader using yt-dlp
Install required package: pip install yt-dlp
"""

import yt_dlp
import subprocess
from pathlib import Path


QUALITY_MENU = {
    "1": "2160",
    "2": "1440",
    "3": "1080",
    "4": "720",
    "5": "480",
}
VALID_QUALITIES = set(QUALITY_MENU.values())


def check_ffmpeg():
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_playlist_info(url):
    ydl_opts = {'quiet': True, 'extract_flat': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info
    except Exception as e:
        print(f"Error fetching playlist info: {str(e)}")
        return None


def download_playlist(url, output_path="./downloads", quality="1080", use_ffmpeg=True):
    """
    Download all videos in a playlist.

    Args:
        url (str): YouTube playlist URL
        output_path (str): Base directory to save videos
        quality (str): Max resolution (e.g. 2160, 1440, 1080, 720)
        use_ffmpeg (bool): Merge separate video+audio streams via FFmpeg
    """
    Path(output_path).mkdir(parents=True, exist_ok=True)

    if use_ffmpeg:
        fmt = f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]'
    else:
        fmt = f'best[height<={quality}]/best'

    ydl_opts = {
        'format': fmt,
        # Save each playlist in its own subfolder named after the playlist
        'outtmpl': f'{output_path}/%(playlist_title)s/%(playlist_index)s - %(title)s.%(ext)s',
        # Skip videos that have already been downloaded
        'download_archive': f'{output_path}/downloaded.txt',
        'ignoreerrors': True,  # Skip unavailable videos instead of stopping
    }

    if use_ffmpeg:
        ydl_opts['merge_output_format'] = 'mp4'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        print("\nPlaylist download completed!")
    except Exception as e:
        print(f"Error: {str(e)}")


def download_playlist_audio(url, output_path="./downloads"):
    """Download all videos in a playlist as MP3 audio."""
    Path(output_path).mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{output_path}/%(playlist_title)s/%(playlist_index)s - %(title)s.%(ext)s',
        'download_archive': f'{output_path}/downloaded.txt',
        'ignoreerrors': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }] if check_ffmpeg() else [],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        print("\nPlaylist audio download completed!")
    except Exception as e:
        print(f"Error: {str(e)}")


def main():
    print("YouTube Playlist Downloader")
    print("=" * 30)

    has_ffmpeg = check_ffmpeg()
    if has_ffmpeg:
        print("✓ FFmpeg detected - High quality downloads available")
    else:
        print("⚠ FFmpeg not found - Limited to pre-merged formats (max ~1080p)")

    while True:
        playlist_url = input("\nEnter YouTube playlist URL (or 'quit' to exit): ").strip()

        if playlist_url.lower() in ['quit', 'exit', 'q']:
            print("Goodbye!")
            break

        if not playlist_url:
            print("Please enter a valid URL!")
            continue

        if not ("youtube.com" in playlist_url or "youtu.be" in playlist_url):
            print("Please enter a valid YouTube URL!")
            continue

        # Show playlist info before downloading
        print("\nFetching playlist info...")
        info = get_playlist_info(playlist_url)
        if info:
            title = info.get('title', 'Unknown Playlist')
            count = info.get('playlist_count') or len(info.get('entries', []))
            print(f"Playlist : {title}")
            print(f"Videos   : {count}")

        print("\nDownload Options:")
        print("1. Download all videos (best quality)")
        print("2. Download all videos (choose quality)")
        print("3. Download audio only (MP3)")
        print("4. Enter new URL")

        choice = input("\nSelect option (1-4): ").strip()

        if choice == "1":
            use_ffmpeg = has_ffmpeg
            quality = "2160"
            if use_ffmpeg:
                print("\nDownloading playlist at best quality (up to 4K, with FFmpeg)...")
            else:
                print("\nDownloading playlist at best pre-merged quality (~720p, no FFmpeg)...")
            download_playlist(playlist_url, quality=quality, use_ffmpeg=use_ffmpeg)

        elif choice == "2":
            print("\nSelect quality:")
            print("1. 2160 (4K)")
            print("2. 1440 (2K)")
            print("3. 1080 (Full HD)")
            print("4. 720  (HD)")
            print("5. 480  (SD)")
            sel = input("Enter choice (1-5 or resolution): ").strip()
            quality = QUALITY_MENU.get(sel) or (sel if sel in VALID_QUALITIES else None)
            if quality is None:
                print("Invalid choice! Pick 1-5 or a valid resolution.")
                continue
            use_ffmpeg = has_ffmpeg
            print(f"\nDownloading playlist at {quality}p...")
            download_playlist(playlist_url, quality=quality, use_ffmpeg=use_ffmpeg)

        elif choice == "3":
            print("\nDownloading playlist as MP3 audio...")
            download_playlist_audio(playlist_url)

        elif choice == "4":
            continue

        else:
            print("Invalid option! Please choose 1-4.")
            continue

        another = input("\nDownload another playlist? (y/n): ").strip().lower()
        if another not in ['y', 'yes']:
            print("Goodbye!")
            break


if __name__ == "__main__":
    main()
