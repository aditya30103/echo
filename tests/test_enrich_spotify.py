"""Tests for enrich_spotify batch-flush resilience.

Background: the original implementation accumulated all enriched rows in memory
and called insert_all() once at the end of the loop. When Spotify's daily
quota hit at 15% (651/4355 tracks), the SystemExit(1) at SpotifyClient.search
discarded ~75 minutes of in-memory work. The fix flushes every
BATCH_FLUSH_EVERY rows AND in a finally block so partial progress always
lands in spotify_tracks. The next run's LEFT JOIN against spotify_tracks
naturally skips anything already enriched.
"""

import sqlite_utils
import pytest

from echo.pipeline import enrich_spotify


def _seed_pending(db: sqlite_utils.Database, n: int) -> None:
    """Create spotify_plays referencing n unique URIs, no spotify_tracks rows."""
    enrich_spotify.init_schema(db)
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
    db["spotify_plays"].insert_all([
        {
            "id": i,
            "ts": "2025-01-01T00:00:00+00:00",
            "ms_played": 100000,
            "spotify_track_uri": f"spotify:track:{i:022d}",
            "track_name":  f"track_{i}",
            "artist_name": f"artist_{i}",
            "content_type": "track",
        }
        for i in range(1, n + 1)
    ])


class _FakeClient:
    """SpotifyClient stub. Returns a synthetic match for the first
    `succeed_until` calls, then raises SystemExit(1) like the real quota path.
    """
    def __init__(self, succeed_until: int = 9999):
        self.calls = 0
        self.succeed_until = succeed_until

    def search(self, track_name: str, artist_name: str):
        self.calls += 1
        if self.calls > self.succeed_until:
            raise SystemExit(1)
        idx = self.calls
        return {
            "uri":         f"spotify:track:{idx:022d}",  # matches seeded URI
            "name":        track_name,
            "artists":     [{"name": artist_name}],
            "duration_ms": 200_000 + idx,
            "explicit":    bool(idx % 2),
        }

    def close(self): pass


# ── Periodic flush during normal completion ──────────────────────────────────

def test_enrich_flushes_periodically(tmp_path, monkeypatch):
    """Even with no failure, rows must land in batches rather than only at end."""
    monkeypatch.setattr(enrich_spotify, "SLEEP_SEC", 0)  # don't actually sleep
    monkeypatch.setattr(enrich_spotify, "BATCH_FLUSH_EVERY", 10)

    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed_pending(db, n=25)

    enrich_spotify.enrich(db, _FakeClient(succeed_until=25), limit=None)

    assert db["spotify_tracks"].count == 25
    sample = next(db.execute(
        "SELECT duration_ms, uri_verified FROM spotify_tracks LIMIT 1"
    ))
    assert sample[0] > 200_000  # duration_ms set
    assert sample[1] == 1       # verified=1 since URIs matched


# ── Finally-block resilience: quota mid-loop ─────────────────────────────────

def test_enrich_persists_partial_progress_on_quota_systemexit(tmp_path, monkeypatch):
    """SystemExit(1) from the quota path must NOT discard in-memory rows.

    Regression guard for the 2026-05-17 incident: 651/4355 enriched tracks
    were thrown away because the single insert_all happened after the loop.
    """
    monkeypatch.setattr(enrich_spotify, "SLEEP_SEC", 0)
    monkeypatch.setattr(enrich_spotify, "BATCH_FLUSH_EVERY", 50)  # > succeed_until on purpose

    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed_pending(db, n=100)

    # Quota fires on call #16, so 15 rows enriched + appended before the raise.
    with pytest.raises(SystemExit):
        enrich_spotify.enrich(db, _FakeClient(succeed_until=15), limit=None)

    # All 15 partial enrichments must have landed via the finally block,
    # not just whatever the periodic batch flushed.
    assert db["spotify_tracks"].count == 15


def test_enrich_persists_partial_progress_on_generic_exception(tmp_path, monkeypatch):
    """Network errors, KeyboardInterrupt, etc. should also not lose progress."""
    monkeypatch.setattr(enrich_spotify, "SLEEP_SEC", 0)
    monkeypatch.setattr(enrich_spotify, "BATCH_FLUSH_EVERY", 100)

    db = sqlite_utils.Database(tmp_path / "echo.db")
    _seed_pending(db, n=50)

    class _BoomClient:
        def __init__(self): self.calls = 0
        def search(self, track_name, artist_name):
            self.calls += 1
            if self.calls > 7:
                raise RuntimeError("simulated network failure")
            idx = self.calls
            return {
                "uri":         f"spotify:track:{idx:022d}",
                "name":        track_name,
                "artists":     [{"name": artist_name}],
                "duration_ms": 200_000 + idx,
                "explicit":    bool(idx % 2),
            }
        def close(self): pass

    with pytest.raises(RuntimeError):
        enrich_spotify.enrich(db, _BoomClient(), limit=None)

    assert db["spotify_tracks"].count == 7
