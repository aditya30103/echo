"""Synthetic Takeout fixture builders for integration tests.

Each builder returns a Path to a freshly-built zip in tmp_path. The zip
contents match the JSON / CSV / ICS shapes that `echo.pipeline.ingest`'s
load_* functions parse:

  - build_activity_zip  -> Takeout/My Activity/{YouTube,Search,Discover,Google Pay}/MyActivity.json
  - build_youtube_zip   -> Takeout/YouTube and YouTube Music/{history,playlists}/...
  - build_calendar_zip  -> Takeout/Calendar/<name>.ics

Designed for a "minimum viable for detect.py" volume: ~40 watches spread
across 12 weeks so PELT has enough weekly signal density (MIN_WATCHES=3,
MIN_CHAPTER_WKS=8) to find at least one chapter.

The shapes mimic real Google Takeout closely enough that ingest.run(config)
exercises the real loader code paths - not a unit test of the loaders, but
an end-to-end smoke that catches packaging / config-wiring regressions.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Stable test data ──────────────────────────────────────────────────────────

_BASE_TIME = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)

# 12 channels (cycled across watch entries to give detect.py varied weekly signals)
_CHANNELS: tuple[tuple[str, str], ...] = (
    ("Fake Tech Channel",      "UCfake_tech____________"),
    ("Fake Music Channel",     "UCfake_music___________"),
    ("Fake News Channel",      "UCfake_news____________"),
    ("Fake Sports Channel",    "UCfake_sports__________"),
    ("Fake Edu Channel",       "UCfake_edu_____________"),
    ("Fake Science Channel",   "UCfake_science_________"),
    ("Fake Comedy Channel",    "UCfake_comedy__________"),
    ("Fake Gaming Channel",    "UCfake_gaming__________"),
    ("Fake Vlog Channel",      "UCfake_vlog____________"),
    ("Fake DIY Channel",       "UCfake_diy_____________"),
    ("Fake Food Channel",      "UCfake_food____________"),
    ("Fake Travel Channel",    "UCfake_travel__________"),
)


def _video_id(n: int) -> str:
    """Stable 11-char video ID for index n. Matches YouTube's video-ID format."""
    return f"fake{n:07d}"  # 11 chars total


def _watch_entry(idx: int, when: datetime) -> dict:
    """One activity-style watch entry matching the shape that load_watches parses."""
    channel_name, channel_id = _CHANNELS[idx % len(_CHANNELS)]
    return {
        "header": "YouTube",
        "title": f"Watched Fake Video {idx}",
        "titleUrl": f"https://www.youtube.com/watch?v={_video_id(idx)}",
        "subtitles": [
            {
                "name": channel_name,
                "url":  f"https://www.youtube.com/channel/{channel_id}",
            }
        ],
        "time": when.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "details": [],  # not "From Google Ads" so _is_ad returns False
    }


def _yt_search_entry(query: str, when: datetime) -> dict:
    return {
        "header": "YouTube",
        "title": f"Searched for {query}",
        "time": when.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }


def _google_search_entry(query: str, when: datetime) -> dict:
    return {
        "header": "Search",
        "title": f"Searched for {query}",
        "time": when.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }


def _discover_entry(topics: list[str], viewed: list[str], when: datetime) -> dict:
    """One discover-feed snapshot. `viewed` is a subset of `topics`."""
    details = [{"name": t} for t in topics if t not in viewed]
    details.extend({"name": f"{t} - viewed"} for t in viewed)
    return {
        "header": "Discover",
        "title": "Saw an article",
        "time": when.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "details": details,
    }


def _transaction_entry(direction: str, amount: int, when: datetime) -> dict:
    """`direction` is 'Sent'/'Paid' (-> sent) or 'Received'. Matches load_transactions parser."""
    return {
        "header": "Google Pay",
        "title": f"{direction} ₹{amount}",  # ₹ symbol
        "time": when.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }


def _watch_entries_dense(count: int = 40, span_weeks: int = 12) -> list[dict]:
    """Build `count` watches spread evenly across `span_weeks` weeks.

    Default = 40 watches / 12 weeks ≈ 3.3 watches/week, just above detect.py's
    MIN_WATCHES=3 threshold so PELT doesn't see the whole span as sparse.
    """
    span = timedelta(weeks=span_weeks)
    step = span / count
    return [_watch_entry(i, _BASE_TIME + step * i) for i in range(count)]


# ── Public builders ──────────────────────────────────────────────────────────


def build_activity_zip(tmp_path: Path) -> Path:
    """Build a My Activity Takeout zip into tmp_path/sample-activity.zip.

    Includes YouTube watches (the PRIMARY watches source) + Google searches +
    Discover snapshots + Google Pay transactions.
    """
    yt_entries     = _watch_entries_dense()
    search_entries = [
        _google_search_entry("how to write a fixture",  _BASE_TIME + timedelta(days=2)),
        _google_search_entry("synthetic test data",     _BASE_TIME + timedelta(days=10)),
    ]
    discover_entries = [
        _discover_entry(["Python", "Testing", "CLI"],         viewed=["Testing"],
                        when=_BASE_TIME + timedelta(days=1)),
        _discover_entry(["Open Source", "Personal Tools"],     viewed=[],
                        when=_BASE_TIME + timedelta(days=8)),
    ]
    txn_entries = [
        _transaction_entry("Paid",     150, _BASE_TIME + timedelta(days=3)),
        _transaction_entry("Sent",      75, _BASE_TIME + timedelta(days=5)),
        _transaction_entry("Received", 200, _BASE_TIME + timedelta(days=7)),
    ]

    path = tmp_path / "sample-activity.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Takeout/My Activity/YouTube/MyActivity.json",     json.dumps(yt_entries))
        zf.writestr("Takeout/My Activity/Search/MyActivity.json",      json.dumps(search_entries))
        zf.writestr("Takeout/My Activity/Discover/MyActivity.json",    json.dumps(discover_entries))
        zf.writestr("Takeout/My Activity/Google Pay/MyActivity.json",  json.dumps(txn_entries))
    return path


def build_youtube_zip(tmp_path: Path) -> Path:
    """Build a YouTube Takeout zip into tmp_path/sample-youtube.zip.

    Includes watch-history (5 supplemental watches), search-history, Watch Later.
    """
    # 5 supplemental watches; ingest's UNIQUE constraint will dedupe overlap with
    # the activity zip (we deliberately use different video IDs to test the
    # union path, not just the dedup).
    yt_history = [
        _watch_entry(100 + i, _BASE_TIME + timedelta(days=14 + i * 3))
        for i in range(5)
    ]
    yt_searches = [
        _yt_search_entry("first test query",  _BASE_TIME + timedelta(days=4)),
        _yt_search_entry("second test query", _BASE_TIME + timedelta(days=9)),
        _yt_search_entry("third test query",  _BASE_TIME + timedelta(days=15)),
    ]
    watch_later_csv = io.StringIO()
    writer = csv.writer(watch_later_csv)
    writer.writerow(["Video ID", "Added At"])
    writer.writerow([_video_id(200), (_BASE_TIME + timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%S.000Z")])
    writer.writerow([_video_id(201), (_BASE_TIME + timedelta(days=21)).strftime("%Y-%m-%dT%H:%M:%S.000Z")])

    path = tmp_path / "sample-youtube.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Takeout/YouTube and YouTube Music/history/watch-history.json",
                    json.dumps(yt_history))
        zf.writestr("Takeout/YouTube and YouTube Music/history/search-history.json",
                    json.dumps(yt_searches))
        zf.writestr("Takeout/YouTube and YouTube Music/playlists/Watch later-videos.csv",
                    watch_later_csv.getvalue())
    return path


def build_calendar_zip(tmp_path: Path) -> Path:
    """Build a Calendar Takeout zip into tmp_path/sample-calendar.zip.

    Includes one .ics with 2 events. Matches the raw ICS shape that
    load_calendar_ics parses (DTSTART/DTEND/SUMMARY/CREATED via regex).
    """
    ics_body = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "SUMMARY:Test event one\r\n"
        "DTSTART:20240105T140000Z\r\n"
        "DTEND:20240105T150000Z\r\n"
        "CREATED:20231220T100000Z\r\n"
        "END:VEVENT\r\n"
        "BEGIN:VEVENT\r\n"
        "SUMMARY:Test event two\r\n"
        "DTSTART:20240220T090000Z\r\n"
        "DTEND:20240220T100000Z\r\n"
        "CREATED:20240115T120000Z\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    path = tmp_path / "sample-calendar.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Takeout/Calendar/Personal.ics", ics_body)
    return path


# Public counts the tests can assert against (single source of truth).
EXPECTED_WATCHES      = 40 + 5  # activity + youtube supplement
EXPECTED_YT_SEARCHES  = 3
EXPECTED_G_SEARCHES   = 2
EXPECTED_WATCH_LATER  = 2
EXPECTED_DISCOVER     = 2
EXPECTED_CAL_EVENTS   = 2
EXPECTED_TRANSACTIONS = 3
