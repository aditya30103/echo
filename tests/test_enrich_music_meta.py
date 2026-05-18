"""Tests for enrich_music_meta Tier 1 + helpers.

Mocks pylast at the call-site level via a small _FakeNetwork stub passed
into _tier1 directly. run() is tested by monkeypatching pylast.LastFMNetwork
on the module.

Covers:
- init_schema idempotency (fresh / partial / full)
- build_track_embed_text (track wins / artist fallback / neither / empty vs None / dedupe)
- _tier1 happy path / empty / WSError-skip / idempotent / batch flush / finally-flush
- run() missing-key fail-soft / dry-run
"""

from __future__ import annotations

import json
from pathlib import Path

import pylast
import pytest
import sqlite_utils

from echo.config import APIKeys, EchoConfig
from echo.pipeline import enrich_music_meta as mod


# ── Fake pylast network ─────────────────────────────────────────────────────

class _FakeItem:
    def __init__(self, name: str): self._name = name
    def get_name(self) -> str: return self._name


class _FakeTopItem:
    def __init__(self, name: str): self.item = _FakeItem(name)


class _FakeArtist:
    def __init__(self, result):
        """result is either a list of tag-name strings OR an exception to raise."""
        self._result = result

    def get_top_tags(self, limit: int = 10):
        if isinstance(self._result, Exception):
            raise self._result
        return [_FakeTopItem(t) for t in self._result[:limit]]


class _FakeTrack:
    def __init__(self, result):
        self._result = result
    def get_top_tags(self, limit: int = 10):
        if isinstance(self._result, Exception):
            raise self._result
        return [_FakeTopItem(t) for t in self._result[:limit]]


class _FakeNetwork:
    """Maps artist_name -> tag list OR Exception. Tracks call counts.

    track_mapping (optional) maps (artist_name, track_name) -> tags or Exception.
    """

    def __init__(self, mapping: dict, track_mapping: dict | None = None):
        self.mapping = mapping
        self.track_mapping = track_mapping or {}
        self.calls: list[str] = []
        self.track_calls: list[tuple[str, str]] = []

    def get_artist(self, name: str) -> _FakeArtist:
        self.calls.append(name)
        return _FakeArtist(self.mapping.get(name, []))

    def get_track(self, artist: str, track: str) -> _FakeTrack:
        self.track_calls.append((artist, track))
        return _FakeTrack(self.track_mapping.get((artist, track), []))


def _ws_error(status: str = "6", details: str = "test") -> pylast.WSError:
    """Construct a real pylast.WSError with a specific status code."""
    return pylast.WSError(network=None, status=status, details=details)


# ── DB seeding helper ────────────────────────────────────────────────────────

def _seed_tracks(db: sqlite_utils.Database, rows: list[dict]) -> None:
    """Create spotify_tracks (via init_schema) and insert rows."""
    mod.init_schema(db)
    db["spotify_tracks"].insert_all(rows, replace=True)


# ── init_schema ──────────────────────────────────────────────────────────────

def test_init_schema_fresh_db_adds_all_three_columns(tmp_path):
    db = sqlite_utils.Database(tmp_path / "echo.db")
    mod.init_schema(db)
    cols = {row[1] for row in db.execute("PRAGMA table_info(spotify_tracks)")}
    assert "artist_lastfm_tags" in cols
    assert "lastfm_tags" in cols
    assert "meta_enriched_at" in cols


def test_init_schema_idempotent_on_rerun(tmp_path):
    """Re-running must not raise 'duplicate column' errors."""
    db = sqlite_utils.Database(tmp_path / "echo.db")
    mod.init_schema(db)
    mod.init_schema(db)  # second call is the regression guard
    mod.init_schema(db)  # third for paranoia


def test_init_schema_partial_existing_columns(tmp_path):
    """Adds only the missing columns when one already exists."""
    db = sqlite_utils.Database(tmp_path / "echo.db")
    # Pre-create the base table + ONE of the music-meta columns manually
    db.execute("""
        CREATE TABLE spotify_tracks (
            spotify_track_uri TEXT PRIMARY KEY,
            artist_name       TEXT,
            lastfm_tags       TEXT
        )
    """)
    mod.init_schema(db)  # must not crash on the already-present lastfm_tags
    cols = {row[1] for row in db.execute("PRAGMA table_info(spotify_tracks)")}
    assert "artist_lastfm_tags" in cols
    assert "lastfm_tags" in cols
    assert "meta_enriched_at" in cols


# ── build_track_embed_text ───────────────────────────────────────────────────

def test_build_track_embed_text_track_tags_win_over_artist():
    out = mod.build_track_embed_text(
        track_name="Tum Hi Ho",
        artist_name="Arijit Singh",
        lastfm_tags=["sad", "ballad", "love"],
        artist_lastfm_tags=["bollywood", "Hindi"],
    )
    assert "sad, ballad, love" in out
    assert "bollywood" not in out


def test_build_track_embed_text_artist_tags_used_when_track_tags_missing():
    out = mod.build_track_embed_text(
        track_name="Some Obscure B-Side",
        artist_name="Arijit Singh",
        lastfm_tags=None,
        artist_lastfm_tags=["bollywood", "Hindi", "soundtrack"],
    )
    assert "bollywood, Hindi, soundtrack" in out


def test_build_track_embed_text_neither_returns_just_name_and_artist():
    out = mod.build_track_embed_text(
        track_name="Anonymous Track",
        artist_name="Anonymous Artist",
        lastfm_tags=None,
        artist_lastfm_tags=None,
    )
    assert out == "Anonymous Track by Anonymous Artist"
    assert "tags:" not in out


def test_build_track_embed_text_empty_list_treated_as_no_tags():
    """Empty list (API returned zero tags) and None (not attempted) are the same here."""
    out_empty = mod.build_track_embed_text("X", "Y", [], [])
    out_none  = mod.build_track_embed_text("X", "Y", None, None)
    assert out_empty == out_none == "X by Y"


def test_build_track_embed_text_dedupes_preserving_order():
    out = mod.build_track_embed_text(
        track_name="X", artist_name="Y",
        lastfm_tags=["pop", "rock", "pop", "indie", "rock"],
        artist_lastfm_tags=None,
    )
    assert "tags: pop, rock, indie" in out


# ── _tier1 ───────────────────────────────────────────────────────────────────

def test_tier1_no_pending_artists_is_noop(tmp_path):
    db = sqlite_utils.Database(tmp_path / "echo.db")
    mod.init_schema(db)  # empty table
    net = _FakeNetwork({})
    written = mod._tier1(db, net)
    assert written == 0
    assert net.calls == []


def test_tier1_happy_path_writes_tags_and_marks_enriched(tmp_path):
    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed_tracks(db, [
        {"spotify_track_uri": "spotify:track:0001", "artist_name": "Pritam", "track_name": "Track 1"},
        {"spotify_track_uri": "spotify:track:0002", "artist_name": "Pritam", "track_name": "Track 2"},
        {"spotify_track_uri": "spotify:track:0003", "artist_name": "Taylor Swift", "track_name": "Track 3"},
    ])
    net = _FakeNetwork({
        "Pritam": ["bollywood", "Hindi", "Indian"],
        "Taylor Swift": ["pop", "country"],
    })
    mod._tier1(db, net)

    rows = list(db.execute(
        "SELECT artist_name, artist_lastfm_tags, meta_enriched_at FROM spotify_tracks ORDER BY spotify_track_uri"
    ))
    # Both Pritam rows got the same artist-level tags
    assert json.loads(rows[0][1]) == ["bollywood", "Hindi", "Indian"]
    assert json.loads(rows[1][1]) == ["bollywood", "Hindi", "Indian"]
    # Taylor Swift got hers
    assert json.loads(rows[2][1]) == ["pop", "country"]
    # All three have meta_enriched_at set
    for r in rows:
        assert r[2] is not None
    # API was called exactly twice (one per unique artist), not 3 times
    assert sorted(net.calls) == ["Pritam", "Taylor Swift"]


def test_tier1_zero_tags_returned_writes_empty_array_not_null(tmp_path):
    """Distinguishes 'API succeeded with no community data' from 'API failed'."""
    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed_tracks(db, [
        {"spotify_track_uri": "spotify:track:0001", "artist_name": "Obscure DIY Artist", "track_name": "X"},
    ])
    net = _FakeNetwork({"Obscure DIY Artist": []})  # API returns empty list
    mod._tier1(db, net)
    row = next(db.execute(
        "SELECT artist_lastfm_tags, meta_enriched_at FROM spotify_tracks LIMIT 1"
    ))
    assert row[0] == "[]"           # explicit empty array, not NULL
    assert row[1] is not None       # meta_enriched_at set so we don't retry


def test_tier1_wserror_writes_null_and_continues_loop(tmp_path):
    """One failing artist must not abort the whole batch."""
    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed_tracks(db, [
        {"spotify_track_uri": "spotify:track:0001", "artist_name": "GoodArtist", "track_name": "A"},
        {"spotify_track_uri": "spotify:track:0002", "artist_name": "MissingArtist", "track_name": "B"},
        {"spotify_track_uri": "spotify:track:0003", "artist_name": "AnotherGood", "track_name": "C"},
    ])
    net = _FakeNetwork({
        "GoodArtist":     ["rock"],
        "MissingArtist":  _ws_error(status="6", details="invalid resource"),
        "AnotherGood":    ["jazz"],
    })
    mod._tier1(db, net)

    rows = {
        r[0]: (r[1], r[2])
        for r in db.execute(
            "SELECT artist_name, artist_lastfm_tags, meta_enriched_at FROM spotify_tracks"
        )
    }
    assert json.loads(rows["GoodArtist"][0]) == ["rock"]
    assert rows["MissingArtist"][0] is None           # NULL on miss
    assert rows["MissingArtist"][1] is not None       # but meta_enriched_at set
    assert json.loads(rows["AnotherGood"][0]) == ["jazz"]


def test_tier1_idempotent_on_rerun_makes_zero_api_calls(tmp_path):
    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed_tracks(db, [
        {"spotify_track_uri": "spotify:track:0001", "artist_name": "Pritam", "track_name": "X"},
    ])
    net1 = _FakeNetwork({"Pritam": ["bollywood"]})
    mod._tier1(db, net1)
    assert net1.calls == ["Pritam"]

    # Second run — discovery query should find zero pending artists
    net2 = _FakeNetwork({"Pritam": ["bollywood"]})
    written = mod._tier1(db, net2)
    assert written == 0
    assert net2.calls == []  # LEFT JOIN / meta_enriched_at NULL filter excluded Pritam


def test_tier1_dedupes_duplicate_tags_from_api(tmp_path):
    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed_tracks(db, [
        {"spotify_track_uri": "spotify:track:0001", "artist_name": "Dupey", "track_name": "X"},
    ])
    net = _FakeNetwork({"Dupey": ["pop", "rock", "pop", "indie", "rock"]})
    mod._tier1(db, net)
    row = next(db.execute("SELECT artist_lastfm_tags FROM spotify_tracks LIMIT 1"))
    assert json.loads(row[0]) == ["pop", "rock", "indie"]


def test_tier1_batch_flush_persists_mid_loop(tmp_path, monkeypatch):
    """Periodic flush must land rows during the loop, not only at the end."""
    monkeypatch.setattr(mod, "BATCH_FLUSH_EVERY", 3)

    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed_tracks(db, [
        {"spotify_track_uri": f"spotify:track:{i:04d}", "artist_name": f"Artist{i}",
         "track_name": f"Track{i}"}
        for i in range(1, 8)
    ])
    net = _FakeNetwork({f"Artist{i}": [f"tag{i}"] for i in range(1, 8)})
    mod._tier1(db, net)

    enriched = db.execute(
        "SELECT COUNT(*) FROM spotify_tracks WHERE meta_enriched_at IS NOT NULL"
    ).fetchone()[0]
    assert enriched == 7


def test_tier1_finally_flushes_on_unexpected_exception(tmp_path, monkeypatch):
    """Transport-level exception (non-WSError) must still flush prior rows."""
    monkeypatch.setattr(mod, "BATCH_FLUSH_EVERY", 100)  # never auto-flushes in this run

    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed_tracks(db, [
        {"spotify_track_uri": f"spotify:track:{i:04d}", "artist_name": f"Artist{i}",
         "track_name": f"Track{i}"}
        for i in range(1, 11)
    ])

    class _BoomNet:
        def __init__(self): self.calls = 0
        def get_artist(self, name):
            self.calls += 1
            if self.calls > 4:
                # non-WSError escapes the per-artist try/except
                raise RuntimeError("simulated network failure")
            return _FakeArtist([f"tag{self.calls}"])

    with pytest.raises(RuntimeError):
        mod._tier1(db, _BoomNet())

    # Without the finally-flush, all 4 enrichments would be lost.
    enriched = db.execute(
        "SELECT COUNT(*) FROM spotify_tracks WHERE meta_enriched_at IS NOT NULL"
    ).fetchone()[0]
    assert enriched == 4


def test_tier1_rate_limit_retries_via_call_with_retry(tmp_path, monkeypatch):
    """WSError(status=29) is rate-limit; _call_with_retry must retry not surface."""
    monkeypatch.setattr(mod, "RETRY_BASE_WAIT_SEC", 0)  # no sleep in tests

    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed_tracks(db, [
        {"spotify_track_uri": "spotify:track:0001", "artist_name": "Flaky", "track_name": "X"},
    ])

    class _FlakyArtist:
        def __init__(self):
            self.attempts = 0
        def get_top_tags(self, limit=10):
            self.attempts += 1
            if self.attempts < 2:
                raise _ws_error(status="29", details="rate limited")
            return [_FakeTopItem("rock")]

    flaky = _FlakyArtist()

    class _FlakyNet:
        def get_artist(self, name): return flaky

    mod._tier1(db, _FlakyNet())
    assert flaky.attempts == 2  # one fail + one success
    row = next(db.execute("SELECT artist_lastfm_tags FROM spotify_tracks LIMIT 1"))
    assert json.loads(row[0]) == ["rock"]


# ── _tier2 ───────────────────────────────────────────────────────────────────

def _seed_plays(db: sqlite_utils.Database, plays: list[tuple[str, int]]) -> None:
    """Create spotify_plays and seed with (uri, count) tuples."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS spotify_plays (
            id INTEGER PRIMARY KEY,
            ts TEXT NOT NULL,
            ms_played INTEGER NOT NULL DEFAULT 0,
            spotify_track_uri TEXT,
            track_name TEXT,
            artist_name TEXT,
            content_type TEXT NOT NULL
        )
    """)
    rows = []
    next_id = 1
    for uri, count in plays:
        for _ in range(count):
            rows.append({
                "id": next_id,
                "ts": "2025-01-01T00:00:00+00:00",
                "ms_played": 200000,
                "spotify_track_uri": uri,
                "track_name": None,  # tier2 reads from spotify_tracks, not plays
                "artist_name": None,
                "content_type": "track",
            })
            next_id += 1
    db["spotify_plays"].insert_all(rows)


def test_tier2_top_n_zero_is_noop(tmp_path):
    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed_tracks(db, [
        {"spotify_track_uri": "spotify:track:0001", "artist_name": "A", "track_name": "T1"},
    ])
    _seed_plays(db, [("spotify:track:0001", 5)])
    net = _FakeNetwork({}, track_mapping={("A", "T1"): ["pop"]})
    written = mod._tier2(db, net, top_n=0)
    assert written == 0
    assert net.track_calls == []


def test_tier2_processes_top_n_by_play_count(tmp_path):
    """Most-played tracks come first; tracks past top_n are not processed."""
    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed_tracks(db, [
        {"spotify_track_uri": f"spotify:track:{i:04d}", "artist_name": f"A{i}",
         "track_name": f"T{i}"} for i in range(1, 6)
    ])
    # Inverse play counts: T1 has 1 play, T5 has 5 plays
    _seed_plays(db, [(f"spotify:track:{i:04d}", i) for i in range(1, 6)])
    net = _FakeNetwork({}, track_mapping={
        (f"A{i}", f"T{i}"): [f"tag{i}"] for i in range(1, 6)
    })

    # top_n=2 should pick the 2 most-played: T5 (5 plays) and T4 (4 plays)
    mod._tier2(db, net, top_n=2)

    assert sorted(net.track_calls) == [("A4", "T4"), ("A5", "T5")]
    enriched_uris = sorted(
        row[0] for row in db.execute(
            "SELECT spotify_track_uri FROM spotify_tracks WHERE lastfm_tags IS NOT NULL"
        )
    )
    assert enriched_uris == ["spotify:track:0004", "spotify:track:0005"]


def test_tier2_top_n_larger_than_available_processes_all(tmp_path):
    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed_tracks(db, [
        {"spotify_track_uri": "spotify:track:0001", "artist_name": "A1", "track_name": "T1"},
        {"spotify_track_uri": "spotify:track:0002", "artist_name": "A2", "track_name": "T2"},
    ])
    _seed_plays(db, [("spotify:track:0001", 1), ("spotify:track:0002", 1)])
    net = _FakeNetwork({}, track_mapping={
        ("A1", "T1"): ["pop"],
        ("A2", "T2"): ["rock"],
    })
    mod._tier2(db, net, top_n=999)
    assert len(net.track_calls) == 2


def test_tier2_wserror_writes_empty_array_continues(tmp_path):
    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed_tracks(db, [
        {"spotify_track_uri": "spotify:track:0001", "artist_name": "A1", "track_name": "T1"},
        {"spotify_track_uri": "spotify:track:0002", "artist_name": "A2", "track_name": "T2"},
    ])
    _seed_plays(db, [("spotify:track:0001", 5), ("spotify:track:0002", 4)])
    net = _FakeNetwork({}, track_mapping={
        ("A1", "T1"): _ws_error(status="6", details="not found"),
        ("A2", "T2"): ["jazz"],
    })
    mod._tier2(db, net, top_n=2)

    rows = {r[0]: r[1] for r in db.execute(
        "SELECT spotify_track_uri, lastfm_tags FROM spotify_tracks"
    )}
    assert rows["spotify:track:0001"] == "[]"          # miss -> empty array
    assert json.loads(rows["spotify:track:0002"]) == ["jazz"]


def test_tier2_idempotent_skips_already_enriched(tmp_path):
    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed_tracks(db, [
        {"spotify_track_uri": "spotify:track:0001", "artist_name": "A1", "track_name": "T1"},
    ])
    _seed_plays(db, [("spotify:track:0001", 5)])
    net1 = _FakeNetwork({}, track_mapping={("A1", "T1"): ["pop"]})
    mod._tier2(db, net1, top_n=10)
    assert net1.track_calls == [("A1", "T1")]

    # Second run: discovery filter (lastfm_tags IS NULL) excludes this URI
    net2 = _FakeNetwork({}, track_mapping={("A1", "T1"): ["pop"]})
    written = mod._tier2(db, net2, top_n=10)
    assert written == 0
    assert net2.track_calls == []


def test_tier2_only_considers_tracks_in_spotify_tracks(tmp_path):
    """Tracks in spotify_plays but missing from spotify_tracks are skipped.

    Otherwise we'd try to UPDATE a non-existent row and silently no-op.
    """
    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed_tracks(db, [
        {"spotify_track_uri": "spotify:track:0001", "artist_name": "A1", "track_name": "T1"},
    ])
    # T2 is in spotify_plays but NOT in spotify_tracks (Spotify enrichment hasn't reached it)
    _seed_plays(db, [
        ("spotify:track:0001", 5),
        ("spotify:track:0002", 100),  # heavily played but unenriched on Spotify side
    ])
    net = _FakeNetwork({}, track_mapping={("A1", "T1"): ["pop"]})
    mod._tier2(db, net, top_n=10)

    assert net.track_calls == [("A1", "T1")]  # only the in-spotify_tracks one


# ── run() entry point ────────────────────────────────────────────────────────

def _empty_config(tmp_path: Path, lastfm: str | None = None) -> EchoConfig:
    cfg = EchoConfig(data_dir=tmp_path)
    cfg.api_keys = APIKeys(lastfm=lastfm)
    return cfg


def test_run_missing_key_exits_zero_with_setup_message(tmp_path, capsys):
    cfg = _empty_config(tmp_path, lastfm=None)
    mod.run(cfg)  # MUST NOT raise SystemExit
    captured = capsys.readouterr()
    assert "LASTFM_API_KEY not set" in captured.out
    assert "last.fm/api/account/create" in captured.out


def test_run_dry_run_skips_api_and_returns_zero(tmp_path, monkeypatch, capsys):
    """--dry-run reports counts without instantiating pylast."""
    cfg = _empty_config(tmp_path, lastfm="fake-key")
    # Seed some pending data so the count > 0
    db = sqlite_utils.Database(cfg.db_path)
    mod.init_schema(db)
    db["spotify_tracks"].insert(
        {"spotify_track_uri": "spotify:track:0001", "artist_name": "Pritam", "track_name": "X"},
        pk="spotify_track_uri", replace=True,
    )
    _seed_plays(db, [("spotify:track:0001", 5)])

    sentinel = {"constructed": False}
    class _Boom:
        def __init__(self, *a, **k): sentinel["constructed"] = True
        def enable_rate_limit(self): pass
    monkeypatch.setattr(mod.pylast, "LastFMNetwork", _Boom)

    mod.run(cfg, dry_run=True)
    out = capsys.readouterr().out
    assert "Tier 1 pending=" in out
    assert "dry-run" in out
    assert sentinel["constructed"] is False


def test_run_skips_gracefully_when_spotify_plays_missing(tmp_path, capsys):
    """Fresh install (no ingest yet) should skip cleanly, not crash."""
    cfg = _empty_config(tmp_path, lastfm="fake-key")
    db = sqlite_utils.Database(cfg.db_path)
    mod.init_schema(db)  # creates spotify_tracks but NOT spotify_plays

    mod.run(cfg)  # must not raise
    out = capsys.readouterr().out
    assert "spotify_plays not present" in out
    assert "echo ingest" in out
