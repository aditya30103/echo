"""Tests for `echo enrich-music-meta` CLI integration.

Covers:
- _PIPELINE_STEPS contains "enrich-music-meta" in the right position
- `echo enrich-music-meta --dry-run` exits 0 (fail-soft on missing key)
- `echo run --skip-enrich-music-meta` removes the step from the run plan
"""

from __future__ import annotations

import re
import sqlite_utils
from typer.testing import CliRunner

from echo.cli.main import app, _PIPELINE_STEPS
from echo.pipeline import enrich_music_meta as mod


def _strip_ansi(s: str) -> str:
    return re.sub(r'\x1b\[[0-9;]*m', '', s)


def test_pipeline_steps_includes_enrich_music_meta_after_spotify():
    """Position matters: must run AFTER enrich-spotify, BEFORE detect."""
    assert "enrich-music-meta" in _PIPELINE_STEPS
    i_spotify = _PIPELINE_STEPS.index("enrich-spotify")
    i_music = _PIPELINE_STEPS.index("enrich-music-meta")
    i_detect = _PIPELINE_STEPS.index("detect")
    assert i_spotify < i_music < i_detect


def test_cli_enrich_music_meta_help_works():
    runner = CliRunner()
    result = runner.invoke(app, ["enrich-music-meta", "--help"])
    assert result.exit_code == 0
    # Strip ANSI escape codes — CI outputs color, Windows terminal does not.
    # Without stripping, "--top-n" appears as "--top\x1b[1;36m-n" and fails `in`.
    clean = _strip_ansi(result.stdout)
    assert "--top-n" in clean
    assert "--dry-run" in clean


def test_cli_enrich_music_meta_missing_key_exits_zero(tmp_path, monkeypatch):
    """Missing LASTFM_API_KEY must be fail-soft, not exit 1."""
    monkeypatch.setenv("ECHO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    # Make sure no .env in cwd leaks a key in
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(app, ["enrich-music-meta"])
    assert result.exit_code == 0, result.stdout
    assert "LASTFM_API_KEY not set" in result.stdout


def test_cli_enrich_music_meta_dry_run_with_key(tmp_path, monkeypatch):
    """--dry-run reports counts without making API calls."""
    monkeypatch.setenv("ECHO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LASTFM_API_KEY", "fake-key-for-test")
    monkeypatch.chdir(tmp_path)

    # Seed schemas so the count queries don't crash on empty install
    db = sqlite_utils.Database(tmp_path / "echo.db")
    mod.init_schema(db)
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

    runner = CliRunner()
    result = runner.invoke(app, ["enrich-music-meta", "--dry-run"])
    assert result.exit_code == 0, result.stdout
    assert "dry-run" in result.stdout
    assert "Tier 1 pending=" in result.stdout


def test_cli_run_skip_enrich_music_meta_removes_step(tmp_path, monkeypatch):
    """--skip-enrich-music-meta drops the step from the planned run."""
    monkeypatch.setenv("ECHO_DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    # Skip every other step too so we don't actually exercise the pipeline
    # (we only care that the planned-step echo reflects the skip)
    runner = CliRunner()
    result = runner.invoke(app, [
        "run",
        "--from", "enrich-music-meta",
        "--skip-enrich-music-meta",
    ])
    # With nothing else after enrich-music-meta until detect, the planned
    # steps line will skip enrich-music-meta but still print detect..embed.
    # We just check the negative assertion - the planned-line excludes it.
    planned_line = next(
        (line for line in result.stdout.splitlines() if "Running pipeline:" in line),
        "",
    )
    assert "enrich-music-meta" not in planned_line, result.stdout
