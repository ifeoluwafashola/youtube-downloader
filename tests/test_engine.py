"""
Unit tests for the pure (no network) parts of yt_engine.

Run from the Yt folder:  python -m pytest tests
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from yt_engine import (  # noqa: E402
    Settings, format_duration, is_video_in_playlist_url, is_youtube_url,
    normalize_quality, parse_selection, unique_stem,
)


@pytest.mark.parametrize("raw,expected", [
    ("best", "best"), ("0", "best"), ("BEST ", "best"),
    ("1", "2160"), ("3", "1080"), ("5", "480"),
    ("1080", "1080"), ("1080p", "1080"), ("720P", "720"),
    ("999", None), ("", None), (None, None), ("abc", None),
])
def test_normalize_quality(raw, expected):
    assert normalize_quality(raw) == expected


@pytest.mark.parametrize("url,ok", [
    ("https://www.youtube.com/watch?v=abc", True),
    ("https://youtu.be/abc", True),
    ("https://music.youtube.com/watch?v=abc", True),
    ("https://m.youtube.com/watch?v=abc", True),
    ("https://notyoutube.com/watch", False),
    ("https://evil.com/?q=youtube.com", False),
    ("youtube.com/watch?v=abc", False),        # no scheme -> no hostname
    ("", False),
])
def test_is_youtube_url(url, ok):
    assert is_youtube_url(url) is ok


def test_is_video_in_playlist_url():
    assert is_video_in_playlist_url("https://www.youtube.com/watch?v=a&list=b")
    assert is_video_in_playlist_url("https://youtu.be/a?list=b")
    assert not is_video_in_playlist_url("https://www.youtube.com/playlist?list=b")
    assert not is_video_in_playlist_url("https://www.youtube.com/watch?v=a")


def test_parse_selection_valid():
    assert parse_selection("1,3,5-8", 10) == ("1,3,5-8", [])
    assert parse_selection("1 3 5-8", 10) == ("1,3,5-8", [])
    assert parse_selection("  ", 10) == ("", [])          # empty means "all"


def test_parse_selection_filters_and_warns():
    items, warnings = parse_selection("0,4,99,7-3,x,2-5", 10)
    assert items == "4,2-5"
    assert len(warnings) == 4


def test_parse_selection_nothing_valid():
    items, warnings = parse_selection("99", 10)
    assert items is None and warnings


def test_format_duration():
    assert format_duration(None) == ""
    assert format_duration(0) == ""
    assert format_duration(65) == "1:05"
    assert format_duration(3725) == "1:02:05"


def test_unique_stem_ignores_intermediate_files(tmp_path):
    (tmp_path / "Foo [1080p].mp4").touch()
    (tmp_path / "Foo [1080p] (1).mp4.part").touch()     # resumable partial
    (tmp_path / "Foo [1080p] (1).f137.mp4").touch()     # unmerged stream
    (tmp_path / "Foo [1080p] (1).webp").touch()         # thumbnail
    assert unique_stem(tmp_path, "Foo [1080p]") == "Foo [1080p] (1)"


def test_unique_stem_counts_finished_files(tmp_path):
    (tmp_path / "Foo.mp3").touch()
    (tmp_path / "Foo (1).mkv").touch()
    assert unique_stem(tmp_path, "Foo") == "Foo (2)"
    assert unique_stem(tmp_path, "Bar") == "Bar"


def test_settings_cookie_opts(tmp_path):
    assert Settings().cookie_opts() == {}
    assert Settings(cookies_from_browser="Chrome").cookie_opts() == {"cookiesfrombrowser": ("chrome",)}
    cookie_file = tmp_path / "cookies.txt"
    assert Settings(cookies_file=cookie_file).cookie_opts() == {}      # missing file -> ignored
    cookie_file.touch()
    assert Settings(cookies_file=cookie_file).cookie_opts() == {"cookiefile": str(cookie_file)}


from yt_engine import format_timestamp, parse_timestamp  # noqa: E402


@pytest.mark.parametrize("raw,expected", [
    ("90", 90), ("1:30", 90), ("1:02:03", 3723), ("90.5", 90.5), ("0", 0),
    ("1m30s", 90), ("2h", 7200), ("45s", 45), ("12:00", 720),
    ("", None), (None, None), ("abc", None), ("1:2:3:4", None), ("-5", None),
])
def test_parse_timestamp(raw, expected):
    assert parse_timestamp(raw) == expected


def test_format_timestamp_is_filename_safe():
    assert format_timestamp(90) == "01.30"
    assert format_timestamp(3723) == "1.02.03"
    assert ":" not in format_timestamp(3723)


from yt_engine import AUDIO_FORMATS, DEFAULT_AUDIO, normalize_audio, user_data_dir  # noqa: E402


@pytest.mark.parametrize("raw,expected", [
    (None, None), (False, None), ("", None),
    (True, DEFAULT_AUDIO), ("mp3", DEFAULT_AUDIO), ("audio", DEFAULT_AUDIO),
    ("wav", "wav-16"), ("WAV-24", "wav-24"), ("mp3-128", "mp3-128"), ("best", "best"),
    ("flac", None), ("mp3-999", None),
])
def test_normalize_audio(raw, expected):
    assert normalize_audio(raw) == expected


def test_audio_formats_are_well_formed():
    for code, (label, codec, quality, extra, tag) in AUDIO_FORMATS.items():
        assert label and isinstance(extra, list)
        if codec == "wav":
            assert "-c:a" in extra and quality is None
        if codec == "mp3":
            assert quality and quality.isdigit()
    assert DEFAULT_AUDIO in AUDIO_FORMATS


def test_user_data_dir_is_per_user_and_exists():
    d = user_data_dir("YouTubeDownloaderTest")
    assert d.is_dir() and str(Path.home()) in str(d)
    d.rmdir()


from yt_engine import human_size  # noqa: E402


def test_human_size():
    assert human_size(None) == "" and human_size(0) == ""
    assert human_size(512) == "512 B"
    assert human_size(1536) == "1.5 KB"
    assert human_size(128.4 * 1024 * 1024) == "128.4 MB"
    assert human_size(3 * 1024 ** 3) == "3.0 GB"
