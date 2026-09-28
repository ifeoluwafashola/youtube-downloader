#!/usr/bin/env python3
"""
YouTube 4K Video Downloader using yt-dlp (Works without FFmpeg)
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

def download_4k_video(url, output_path="./downloads"):
    """
    Download YouTube video in 4K quality (or best available) - No FFmpeg needed
    
    Args:
        url (str): YouTube video URL
        output_path (str): Directory to save the video
    """
    
    # Create output directory if it doesn't exist
    Path(output_path).mkdir(parents=True, exist_ok=True)
    
    # Use merged video+audio when ffmpeg is available (true 4K),
    # otherwise fall back to a single pre-merged file (~720p max)
    if check_ffmpeg():
        fmt = 'bestvideo[height<=2160]+bestaudio/best[height<=2160]'
        ydl_opts = {
            'format': fmt,
            'outtmpl': f'{output_path}/%(title)s.%(ext)s',
            'merge_output_format': 'mp4',
        }
    else:
        ydl_opts = {
            'format': 'best[height<=2160]/best',
            'outtmpl': f'{output_path}/%(title)s.%(ext)s',
        }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Get video info first
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Unknown')
            duration = info.get('duration') or 0
            uploader = info.get('uploader', 'Unknown')
            
            print(f"Title: {title}")
            print(f"Uploader: {uploader}")
            print(f"Duration: {duration//60}:{duration%60:02d}")
            print("Starting download...")
            
            # Download the video
            ydl.download([url])
            print("Download completed successfully!")
            
    except Exception as e:
        print(f"Error downloading video: {str(e)}")

def download_with_custom_quality(url, output_path="./downloads", quality="2160"):
    """
    Download with a specific quality. Uses merged streams when ffmpeg is
    available (needed above ~720p), otherwise a single pre-merged file.

    Args:
        url (str): YouTube video URL
        output_path (str): Directory to save the video
        quality (str): Quality preference (2160, 1440, 1080, 720, etc.)
    """
    
    Path(output_path).mkdir(parents=True, exist_ok=True)
    
    if check_ffmpeg():
        ydl_opts = {
            'format': f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]',
            'outtmpl': f'{output_path}/%(title)s_%(height)sp.%(ext)s',
            'merge_output_format': 'mp4',
        }
    else:
        ydl_opts = {
            'format': f'best[height<={quality}]/best',
            'outtmpl': f'{output_path}/%(title)s_%(height)sp.%(ext)s',
        }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            print(f"Download completed in {quality}p quality!")
    except Exception as e:
        print(f"Error: {str(e)}")

def download_with_ffmpeg_support(url, output_path="./downloads", quality="2160"):
    """
    Download with ffmpeg support (better quality, requires ffmpeg installed)
    
    Args:
        url (str): YouTube video URL
        output_path (str): Directory to save the video
        quality (str): Quality preference (2160, 1440, 1080, 720, etc.)
    """
    
    Path(output_path).mkdir(parents=True, exist_ok=True)
    
    ydl_opts = {
        'format': f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]',
        'outtmpl': f'{output_path}/%(title)s_%(height)sp.%(ext)s',
        'merge_output_format': 'mp4',
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            print(f"Download completed in {quality}p quality with ffmpeg!")
    except Exception as e:
        print(f"Error: {str(e)}")
        print("Tip: This error often means ffmpeg is not installed.")
        print("Try the regular download option instead.")

def check_ffmpeg():
    """
    Check if ffmpeg is available
    """
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def list_available_formats(url):
    """
    List all available video formats for a YouTube video
    """
    ydl_opts = {
        'listformats': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=False)
    except Exception as e:
        print(f"Error listing formats: {str(e)}")

def download_audio_only(url, output_path="./downloads"):
    """
    Download only audio in best quality
    """
    Path(output_path).mkdir(parents=True, exist_ok=True)
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{output_path}/%(title)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }] if check_ffmpeg() else [],
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            print("Audio download completed!")
    except Exception as e:
        print(f"Error downloading audio: {str(e)}")
        if not check_ffmpeg():
            print("Note: Audio conversion requires ffmpeg for best results.")

def main():
    """
    Interactive main function with user input
    """
    print("YouTube 4K Video Downloader")
    print("=" * 30)
    
    # Check ffmpeg availability
    has_ffmpeg = check_ffmpeg()
    if has_ffmpeg:
        print("✓ FFmpeg detected - All features available")
    else:
        print("⚠ FFmpeg not found - Basic download available")
        print("  (Install FFmpeg for better quality and audio conversion)")
    
    while True:
        # Get video URL from user
        video_url = input("\nEnter YouTube video URL (or 'quit' to exit): ").strip()
        
        if video_url.lower() in ['quit', 'exit', 'q']:
            print("Goodbye!")
            break
            
        if not video_url:
            print("Please enter a valid URL!")
            continue
            
        # Validate URL (basic check)
        if not ("youtube.com" in video_url or "youtu.be" in video_url):
            print("Please enter a valid YouTube URL!")
            continue
        
        # Show options menu
        print("\nDownload Options:")
        print("1. Download in 4K (single file - no ffmpeg needed)")
        print("2. Choose specific quality (single file)")
        if has_ffmpeg:
            print("3. Download with ffmpeg support (better quality)")
        print("4. List available formats first")
        print("5. Download audio only")
        print("6. Enter new URL")
        
        max_option = 6 if has_ffmpeg else 5
        choice = input(f"\nSelect option (1-{max_option}): ").strip()
        
        if choice == "1":
            print("\nDownloading in 4K quality (single file)...")
            download_4k_video(video_url)
            
        elif choice == "2":
            print("\nSelect quality:")
            print("1. 2160 (4K)")
            print("2. 1440 (2K)")
            print("3. 1080 (Full HD)")
            print("4. 720 (HD)")
            print("5. 480 (SD)")
            
            sel = input("Enter choice (1-5 or resolution): ").strip()
            quality = QUALITY_MENU.get(sel) or (sel if sel in VALID_QUALITIES else None)
            if quality is not None:
                print(f"\nDownloading in {quality}p quality...")
                download_with_custom_quality(video_url, quality=quality)
            else:
                print("Invalid choice! Pick 1-5 or a valid resolution.")
                
        elif choice == "3" and has_ffmpeg:
            print("\nSelect quality:")
            print("1. 2160 (4K)")
            print("2. 1440 (2K)")
            print("3. 1080 (Full HD)")
            print("4. 720 (HD)")
            print("5. 480 (SD)")
            
            sel = input("Enter choice (1-5 or resolution): ").strip()
            quality = QUALITY_MENU.get(sel) or (sel if sel in VALID_QUALITIES else None)
            if quality is not None:
                print(f"\nDownloading with ffmpeg in {quality}p quality...")
                download_with_ffmpeg_support(video_url, quality=quality)
            else:
                print("Invalid choice! Pick 1-5 or a valid resolution.")
                
        elif choice == ("4" if has_ffmpeg else "3"):
            print("\nListing available formats...")
            list_available_formats(video_url)
            input("\nPress Enter to continue...")
            
        elif choice == ("5" if has_ffmpeg else "4"):
            print("\nDownloading audio only...")
            download_audio_only(video_url)
            
        elif choice == ("6" if has_ffmpeg else "5"):
            continue
            
        else:
            print(f"Invalid option! Please choose 1-{max_option}.")
            continue
        
        # Ask if user wants to download another video
        another = input("\nDownload another video? (y/n): ").strip().lower()
        if another not in ['y', 'yes']:
            print("Goodbye!")
            break

# Run the program
if __name__ == "__main__":
    main()