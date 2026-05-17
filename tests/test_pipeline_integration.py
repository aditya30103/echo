"""End-to-end smoke tests against fresh tmp_path data dirs.

These run the real pipeline `run(config)` functions against the synthetic
Takeout fixtures from tests/fixtures.py. They catch regressions that unit
tests miss:

  - packaging / config wiring (an EchoConfig field that doesn't reach a
    pipeline step would surface here)
  - schema drift (a CREATE TABLE that doesn't match what later steps expect)
  - cross-step contracts (signals.py expecting a column ingest.py stopped writing)

API-dependent steps (enrich, reflect, embed) are NOT exercised here; they
need their HTTP clients mocked and live in a follow-up test module.
"""

from __future__ import annotations

import sqlite_utils
import pytest

from echo.config import APIKeys, EchoConfig, TakeoutPaths
from echo.pipeline import detect, ingest, signals

from tests.fixtures import (
    EXPECTED_CAL_EVENTS,
    EXPECTED_DISCOVER,
    EXPECTED_G_SEARCHES,
    EXPECTED_TRANSACTIONS,
    EXPECTED_WATCHES,
    EXPECTED_WATCH_LATER,
    EXPECTED_YT_SEARCHES,
    build_activity_zip,
    build_calendar_zip,
    build_youtube_zip,
)


# ── Shared fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def sample_zips(tmp_path_factory):
    """Build the three Takeout zips once per test session and reuse.

    Returns a (activity, youtube, calendar) tuple of Path objects pointing at
    freshly-built zips under a session-scoped tmp directory.
    """
    fixture_dir = tmp_path_factory.mktemp("takeout-fixtures")
    return (
        build_activity_zip(fixture_dir),
        build_youtube_zip(fixture_dir),
        build_calendar_zip(fixture_dir),
    )


@pytest.fixture
def fresh_config(tmp_path, sample_zips):
    """Build an EchoConfig pointing at a tmp data_dir + the session zips.

    `tmp_path` is function-scoped: each test gets its own data_dir, so writes
    in one test never leak into another.
    """
    activity, youtube, calendar = sample_zips
    return EchoConfig(
        data_dir=tmp_path,
        takeout=TakeoutPaths(
            youtube_zip=youtube,
            activity_zip=activity,
            calendar_zip=calendar,
            spotify_zip=None,  # not exercising Spotify in this batch
        ),
        api_keys=APIKeys(),  # all empty - we skip API-bound steps
    )


# ── Per-step integration tests ──────────────────────────────────────────────


def test_ingest_populates_every_expected_table(fresh_config):
    """ingest.run produces all expected row counts across 7 tables."""
    ingest.run(fresh_config)

    db = sqlite_utils.Database(fresh_config.db_path)

    assert db["watches"].count         == EXPECTED_WATCHES
    assert db["yt_searches"].count     == EXPECTED_YT_SEARCHES
    assert db["watch_later"].count     == EXPECTED_WATCH_LATER
    assert db["google_searches"].count == EXPECTED_G_SEARCHES
    assert db["discover_feed"].count   == EXPECTED_DISCOVER
    assert db["calendar_events"].count == EXPECTED_CAL_EVENTS
    assert db["transactions"].count    == EXPECTED_TRANSACTIONS
    # Spotify path skipped (no zip configured); table exists but empty.
    assert db["spotify_plays"].count   == 0


def test_ingest_is_idempotent(fresh_config):
    """Re-running ingest doesn't duplicate rows (UNIQUE constraints win)."""
    ingest.run(fresh_config)
    db = sqlite_utils.Database(fresh_config.db_path)
    first_watches = db["watches"].count

    ingest.run(fresh_config)
    second_watches = sqlite_utils.Database(fresh_config.db_path)["watches"].count

    assert first_watches == second_watches == EXPECTED_WATCHES


def test_ingest_handles_missing_optional_zips(tmp_path, sample_zips):
    """ingest.run with only YouTube configured skips activity/calendar gracefully."""
    _, youtube, _ = sample_zips
    cfg = EchoConfig(
        data_dir=tmp_path,
        takeout=TakeoutPaths(youtube_zip=youtube),  # only YouTube
    )
    ingest.run(cfg)

    db = sqlite_utils.Database(cfg.db_path)
    # YouTube supplement watches landed; activity-source watches did not.
    assert db["watches"].count == 5
    assert db["yt_searches"].count == EXPECTED_YT_SEARCHES
    assert db["google_searches"].count == 0
    assert db["calendar_events"].count == 0


def test_signals_runs_after_ingest(fresh_config):
    """signals.run produces watch_signals with one row per watch."""
    ingest.run(fresh_config)
    signals.run(fresh_config)

    db = sqlite_utils.Database(fresh_config.db_path)
    assert db["watch_signals"].count == EXPECTED_WATCHES

    # spotify_signals was created (table exists) but empty (no Spotify zip).
    table_names = {t.name for t in db.tables}
    if "spotify_signals" in table_names:
        assert db["spotify_signals"].count == 0


def test_detect_runs_after_ingest(fresh_config):
    """detect.run produces chapters + chapter_fingerprints.

    With only 12 weeks of fake data, PELT may produce 1 chapter or refuse
    (MIN_CHAPTER_WKS=8); either way it shouldn't crash, and the schema
    should be created.
    """
    ingest.run(fresh_config)
    # detect calls sys.exit(1) if there's no data from 2020+ - but our fixture
    # uses 2024 timestamps, so it should proceed.
    detect.run(fresh_config, penalty=3.0, dry_run=False, plot=False)

    db = sqlite_utils.Database(fresh_config.db_path)
    # Schema present + at least zero rows is the minimum contract;
    # exact chapter count is data-dependent and brittle to PELT tuning.
    assert "chapters" in {t.name for t in db.tables}
    assert "chapter_fingerprints" in {t.name for t in db.tables}
    # With our 40 watches across 12 weeks (~3.3/wk above MIN_WATCHES=3),
    # PELT should produce at least 1 chapter.
    assert db["chapters"].count >= 1


def test_full_no_api_pipeline_dry_run(fresh_config):
    """ingest -> detect -> signals composes cleanly with no API keys configured."""
    ingest.run(fresh_config)
    detect.run(fresh_config, penalty=3.0, dry_run=False, plot=False)
    signals.run(fresh_config)

    db = sqlite_utils.Database(fresh_config.db_path)
    # Final assertion: every non-API table has data and the views are queryable.
    assert db["watches"].count == EXPECTED_WATCHES
    assert db["chapters"].count >= 1
    assert db["watch_signals"].count == EXPECTED_WATCHES

    # The enriched_watches view was created by init_schema and should work
    # even without video_metadata being populated (LEFT JOIN with COALESCE).
    enriched_count = db.execute("SELECT COUNT(*) FROM enriched_watches").fetchone()[0]
    assert enriched_count == EXPECTED_WATCHES
