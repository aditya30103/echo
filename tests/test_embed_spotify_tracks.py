"""Tests for the embed.py spotify_tracks extension (Phase E of Spotify rework).

Covers:
- load_spotify_tracks parses lastfm_tags JSON and uses build_track_embed_text
- load_spotify_tracks filters out un-meta-enriched rows
- write_table for spotify_tracks doesn't drop the other 4 lancedb tables
  (regression guard - the agent's vector_search depends on them being stable)
- ALL_TABLES contains spotify_tracks as the 5th entry
"""

from __future__ import annotations

import json
from pathlib import Path

import lancedb
import sqlite_utils

from echo.config import ALL_TABLES
from echo.pipeline import embed as embed_mod
from echo.pipeline import enrich_music_meta as music_mod


# ── ALL_TABLES contract ──────────────────────────────────────────────────────

def test_all_tables_appends_spotify_tracks_as_fifth():
    assert ALL_TABLES == [
        "reflections",
        "videos",
        "searches",
        "google_searches",
        "spotify_tracks",
    ]


# ── load_spotify_tracks ──────────────────────────────────────────────────────

def _seed(db: sqlite_utils.Database, rows: list[dict]) -> None:
    music_mod.init_schema(db)
    db["spotify_tracks"].insert_all(rows, replace=True, pk="spotify_track_uri")


def test_load_spotify_tracks_filters_unenriched_rows(tmp_path):
    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed(db, [
        {"spotify_track_uri": "spotify:track:0001", "track_name": "T1",
         "artist_name": "A1", "meta_enriched_at": "2026-01-01T00:00:00Z",
         "artist_lastfm_tags": json.dumps(["rock"]),
         "lastfm_tags": None},
        {"spotify_track_uri": "spotify:track:0002", "track_name": "T2",
         "artist_name": "A2", "meta_enriched_at": None,
         "artist_lastfm_tags": None,
         "lastfm_tags": None},
    ])
    recs = embed_mod.load_spotify_tracks(db)
    uris = [r["uri"] for r in recs]
    assert uris == ["spotify:track:0001"]  # un-meta-enriched one excluded


def test_load_spotify_tracks_uses_track_tags_when_present(tmp_path):
    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed(db, [
        {"spotify_track_uri": "spotify:track:0001", "track_name": "Sad Song",
         "artist_name": "Happy Artist",
         "meta_enriched_at": "2026-01-01T00:00:00Z",
         "artist_lastfm_tags": json.dumps(["happy", "pop"]),
         "lastfm_tags": json.dumps(["melancholy", "ballad"])},
    ])
    recs = embed_mod.load_spotify_tracks(db)
    assert "melancholy, ballad" in recs[0]["text"]
    assert "happy" not in recs[0]["text"]   # track tags win


def test_load_spotify_tracks_falls_back_to_artist_tags(tmp_path):
    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed(db, [
        {"spotify_track_uri": "spotify:track:0001", "track_name": "T1",
         "artist_name": "A1",
         "meta_enriched_at": "2026-01-01T00:00:00Z",
         "artist_lastfm_tags": json.dumps(["bollywood", "Hindi"]),
         "lastfm_tags": None},
    ])
    recs = embed_mod.load_spotify_tracks(db)
    assert "bollywood, Hindi" in recs[0]["text"]


def test_load_spotify_tracks_handles_empty_array_tags(tmp_path):
    """lastfm_tags='[]' means Tier 2 attempted with no result - fall through to artist tags."""
    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed(db, [
        {"spotify_track_uri": "spotify:track:0001", "track_name": "T1",
         "artist_name": "A1",
         "meta_enriched_at": "2026-01-01T00:00:00Z",
         "artist_lastfm_tags": json.dumps(["pop"]),
         "lastfm_tags": "[]"},
    ])
    recs = embed_mod.load_spotify_tracks(db)
    assert "tags: pop" in recs[0]["text"]   # artist fallback engaged


def test_load_spotify_tracks_filters_empty_name_or_artist(tmp_path):
    """Empty strings for name/artist would produce garbage embed text."""
    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed(db, [
        {"spotify_track_uri": "spotify:track:0001", "track_name": "",
         "artist_name": "A1",
         "meta_enriched_at": "2026-01-01T00:00:00Z",
         "artist_lastfm_tags": json.dumps(["rock"]),
         "lastfm_tags": None},
        {"spotify_track_uri": "spotify:track:0002", "track_name": "T2",
         "artist_name": "",
         "meta_enriched_at": "2026-01-01T00:00:00Z",
         "artist_lastfm_tags": json.dumps(["pop"]),
         "lastfm_tags": None},
    ])
    recs = embed_mod.load_spotify_tracks(db)
    assert recs == []


def test_load_spotify_tracks_missing_table_returns_empty(tmp_path):
    """Fresh install with no spotify_tracks at all - graceful no-op."""
    db = sqlite_utils.Database(tmp_path / "echo.db")
    # Do NOT call init_schema; the table simply doesn't exist.
    assert embed_mod.load_spotify_tracks(db) == []


# ── lancedb regression: other tables survive spotify_tracks recreate ────────

def test_write_table_spotify_tracks_does_not_drop_other_tables(tmp_path):
    """Regression guard: writing spotify_tracks must not affect the other 4."""
    ldb = lancedb.connect(str(tmp_path / "lancedb"))
    # Seed 4 dummy tables (matching the names the agent expects)
    for name in ("reflections", "videos", "searches", "google_searches"):
        ldb.create_table(
            name,
            data=[{"id": name, "text": "seed", "vector": [0.0] * 4}],
        )
    assert set(ldb.list_tables().tables) == {
        "reflections", "videos", "searches", "google_searches"
    }

    # Now write the new spotify_tracks via the same helper used by embed.run()
    records = [
        {"uri": "spotify:track:0001", "track_name": "T1", "artist_name": "A1",
         "lastfm_tags": "[]", "artist_lastfm_tags": "[]",
         "text": "T1 by A1"},
    ]
    vectors = [[0.1] * 4]
    embed_mod.write_table(ldb, "spotify_tracks", records, vectors)

    # All 5 tables present; the 4 originals are unaffected.
    tables = set(ldb.list_tables().tables)
    assert tables == {
        "reflections", "videos", "searches", "google_searches", "spotify_tracks"
    }
    for name in ("reflections", "videos", "searches", "google_searches"):
        rows = list(ldb.open_table(name).search([0.0, 0.0, 0.0, 0.0]).to_list())
        assert any(r["id"] == name for r in rows), f"{name} got clobbered"


def test_write_table_spotify_tracks_drop_and_recreate_is_idempotent(tmp_path):
    """Second call to write_table replaces, not duplicates."""
    ldb = lancedb.connect(str(tmp_path / "lancedb"))
    base = {"uri": "spotify:track:0001", "track_name": "T1", "artist_name": "A1",
            "lastfm_tags": "[]", "artist_lastfm_tags": "[]", "text": "T1 by A1"}
    embed_mod.write_table(ldb, "spotify_tracks", [base], [[0.1] * 4])
    embed_mod.write_table(ldb, "spotify_tracks", [base], [[0.1] * 4])
    rows = list(ldb.open_table("spotify_tracks").search([0.0] * 4).to_list())
    assert len(rows) == 1   # drop-and-recreate, not append
