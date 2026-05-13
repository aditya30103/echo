"""Tests for IST timezone logic in timeline queries."""

import sqlite3
import pytest
import sqlite_utils


@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    db = sqlite_utils.Database(conn)
    db["watches"].create({
        "id": int,
        "video_id": str,
        "watched_at": str,  # UTC ISO8601
        "title": str,
    }, pk="id")
    db["video_metadata"].create({"video_id": str, "title": str, "channel_title": str}, pk="video_id")
    db["watch_signals"].create({"watch_id": int, "is_rewatch": int, "session_depth": int, "is_search_driven": int}, pk="watch_id")
    db["chapters"].create({"id": int, "label": str, "start_at": str, "end_at": str}, pk="id")
    return db


def ist_to_utc_str(ist_hour, ist_minute=0, date="2022-06-15"):
    """Convert IST time to UTC ISO string for test fixtures."""
    total_minutes = ist_hour * 60 + ist_minute - 330  # subtract IST offset
    h, m = divmod(total_minutes % (24 * 60), 60)
    day = date
    # Handle day rollback
    if total_minutes < 0:
        day = "2022-06-14"
        total_minutes += 24 * 60
        h, m = divmod(total_minutes, 60)
    return f"{day}T{h:02d}:{m:02d}:00"


def test_night_filter_includes_2330_ist(mem_db):
    """23:30 IST watch must appear in night archaeology."""
    mem_db["watches"].insert({"id": 1, "video_id": "v1", "watched_at": ist_to_utc_str(23, 30), "title": "Late video"})
    from api.constants import IST_OFFSET
    rows = mem_db.execute(f"""
        SELECT id FROM watches w
        WHERE strftime('%H', datetime(w.watched_at, '{IST_OFFSET}')) >= '23'
           OR strftime('%H', datetime(w.watched_at, '{IST_OFFSET}')) < '04'
    """).fetchall()
    assert len(rows) == 1


def test_night_filter_includes_0200_ist(mem_db):
    """02:00 IST watch must appear in night archaeology."""
    mem_db["watches"].insert({"id": 2, "video_id": "v2", "watched_at": ist_to_utc_str(2, 0), "title": "2am video"})
    from api.constants import IST_OFFSET
    rows = mem_db.execute(f"""
        SELECT id FROM watches w
        WHERE strftime('%H', datetime(w.watched_at, '{IST_OFFSET}')) >= '23'
           OR strftime('%H', datetime(w.watched_at, '{IST_OFFSET}')) < '04'
    """).fetchall()
    assert len(rows) == 1


def test_night_filter_excludes_1400_ist(mem_db):
    """14:00 IST (afternoon) watch must NOT appear in night archaeology."""
    mem_db["watches"].insert({"id": 3, "video_id": "v3", "watched_at": ist_to_utc_str(14, 0), "title": "Afternoon video"})
    from api.constants import IST_OFFSET
    rows = mem_db.execute(f"""
        SELECT id FROM watches w
        WHERE strftime('%H', datetime(w.watched_at, '{IST_OFFSET}')) >= '23'
           OR strftime('%H', datetime(w.watched_at, '{IST_OFFSET}')) < '04'
    """).fetchall()
    assert len(rows) == 0


def test_night_filter_excludes_0400_ist(mem_db):
    """04:00 IST exactly must NOT appear (boundary is exclusive)."""
    mem_db["watches"].insert({"id": 4, "video_id": "v4", "watched_at": ist_to_utc_str(4, 0), "title": "4am boundary"})
    from api.constants import IST_OFFSET
    rows = mem_db.execute(f"""
        SELECT id FROM watches w
        WHERE strftime('%H', datetime(w.watched_at, '{IST_OFFSET}')) >= '23'
           OR strftime('%H', datetime(w.watched_at, '{IST_OFFSET}')) < '04'
    """).fetchall()
    assert len(rows) == 0
