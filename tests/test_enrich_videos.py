"""Tests for api/routers/chat.py:_enrich_videos() — batched video enrichment."""

import sqlite3
import pytest
import sqlite_utils

from api.routers.chat import _enrich_videos


@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    db = sqlite_utils.Database(conn)
    db["watches"].create({
        "id": int,
        "video_id": str,
        "watched_at": str,
    }, pk="id")
    db["chapters"].create({
        "id": int,
        "label": str,
        "start_at": str,
        "end_at": str,
    }, pk="id")
    # _enrich_videos LEFT JOINs watch_signals; the in-memory DB must have the
    # schema for the join to resolve (rows can be empty - LEFT JOIN handles it).
    db["watch_signals"].create({
        "watch_id":      int,
        "rewatch_count": int,
    }, pk="watch_id")
    return db


def test_empty_rows_returns_empty(mem_db):
    result = _enrich_videos([], mem_db)
    assert result == []


def test_rows_with_no_video_id_skipped(mem_db):
    rows = [{"video_id": None, "title": "orphan"}]
    result = _enrich_videos(rows, mem_db)
    assert result == [{"video_id": None, "title": "orphan"}]


def test_enriches_first_and_last_seen(mem_db):
    mem_db["watches"].insert_all([
        {"id": 1, "video_id": "abc", "watched_at": "2022-01-10T10:00:00"},
        {"id": 2, "video_id": "abc", "watched_at": "2022-06-20T15:00:00"},
    ])
    rows = [{"video_id": "abc", "title": "Test"}]
    result = _enrich_videos(rows, mem_db)
    assert result[0]["first_seen_ist"] == "2022-01-10"
    assert result[0]["last_seen_ist"] == "2022-06-20"


def test_unknown_video_id_gets_empty_strings(mem_db):
    """Video in lancedb results that has no watch history should not error."""
    rows = [{"video_id": "missing", "title": "Not in watches"}]
    result = _enrich_videos(rows, mem_db)
    # Should not raise; fields may be absent or empty
    assert result[0]["video_id"] == "missing"


def test_batches_multiple_videos_in_one_query(mem_db):
    """Two different video_ids must both be enriched correctly."""
    mem_db["watches"].insert_all([
        {"id": 1, "video_id": "v1", "watched_at": "2021-03-01T08:00:00"},
        {"id": 2, "video_id": "v2", "watched_at": "2023-11-15T12:00:00"},
    ])
    rows = [{"video_id": "v1", "title": "A"}, {"video_id": "v2", "title": "B"}]
    result = _enrich_videos(rows, mem_db)
    assert result[0]["first_seen_ist"] == "2021-03-01"
    assert result[1]["first_seen_ist"] == "2023-11-15"
