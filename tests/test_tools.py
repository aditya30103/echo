"""Tests for Sprint 3 tools: run_pelt, run_clustering, run_youtube_lookup, execute_python."""

import os
import json
import pytest
from unittest.mock import patch, MagicMock


# ── run_pelt ──────────────────────────────────────────────────────────────────

def test_pelt_invalid_table():
    from echo.api.tools.pelt_tool import run_pelt
    result = run_pelt(table="nonexistent_table", ts_col="watched_at")
    assert "ERROR" in result or "error" in result.lower()


def test_pelt_invalid_freq():
    from echo.api.tools.pelt_tool import run_pelt
    result = run_pelt(table="watches", ts_col="watched_at", freq="INVALID")
    assert "ERROR" in result or "error" in result.lower()


def test_pelt_happy_path(tmp_path, monkeypatch):
    """Run PELT against a fixture-populated echo.db, not the dev's real one.

    Builds a fresh echo.db via `ingest.run(config)` against the synthetic
    Takeout zips from tests/fixtures.py. Monkeypatches the tool's module-level
    _DB_PATH (resolved at import time from get_db_path()) so the tool reads
    from the fixture DB instead of ~/.echo/echo.db.
    """
    from echo.config import EchoConfig, TakeoutPaths
    from echo.pipeline import ingest
    from echo.api.tools import pelt_tool
    from tests.fixtures import build_activity_zip, build_youtube_zip

    cfg = EchoConfig(
        data_dir=tmp_path,
        takeout=TakeoutPaths(
            activity_zip=build_activity_zip(tmp_path),
            youtube_zip=build_youtube_zip(tmp_path),
        ),
    )
    ingest.run(cfg)
    monkeypatch.setattr(pelt_tool, "_DB_PATH", str(cfg.db_path))

    result = pelt_tool.run_pelt(table="watches", ts_col="watched_at",
                                value_col="*", freq="W", penalty=2.0)
    assert result.startswith("[RAW-COMPUTED]")
    data = json.loads(result[len("[RAW-COMPUTED] "):])
    assert "breakpoint_dates" in data
    assert "segments" in data
    assert isinstance(data["segments"], list)


# ── run_clustering ─────────────────────────────────────────────────────────────

def test_clustering_invalid_table():
    from echo.api.tools.clustering_tool import run_clustering
    result = run_clustering(table="nonexistent_table")
    assert "ERROR" in result


def test_clustering_n_clusters_below_min():
    from echo.api.tools.clustering_tool import run_clustering
    result = run_clustering(table="videos", n_clusters=1)
    assert "ERROR" in result


def test_clustering_n_clusters_exceeds_rows():
    from echo.api.tools.clustering_tool import run_clustering
    # n_clusters=9999 will always exceed actual row count in any realistic table
    result = run_clustering(table="videos", n_clusters=9999)
    assert "ERROR" in result


def test_clustering_happy_path(tmp_path, monkeypatch):
    """Run k-means against a fixture-built lancedb, not the dev's real one.

    Builds a tmp lancedb with 12 unit-norm 1536-dim vectors via
    fixtures.build_lancedb_videos, then monkeypatches the tool's _LANCE_PATH
    so the tool reads from the fixture instead of ~/.echo/lancedb/.
    """
    from echo.api.tools import clustering_tool
    from tests.fixtures import build_lancedb_videos

    lance_dir = build_lancedb_videos(tmp_path, n_rows=12)
    monkeypatch.setattr(clustering_tool, "_LANCE_PATH", str(lance_dir))

    result = clustering_tool.run_clustering(table="videos", n_clusters=3)
    assert result.startswith("[RAW-COMPUTED]")
    data = json.loads(result[len("[RAW-COMPUTED] "):])
    assert "silhouette_score" in data
    assert "clusters" in data
    assert len(data["clusters"]) == 3


# ── run_youtube_lookup ────────────────────────────────────────────────────────

def test_youtube_missing_api_key(monkeypatch):
    from echo.api.tools import youtube_tool

    # `run_youtube_lookup` calls `_load_env` which reads .env via echo.config
    # and may re-populate YOUTUBE_API_KEY from the file on the dev's host.
    # Stub it out so we control exactly what the tool sees.
    monkeypatch.setattr(youtube_tool, "_load_env", lambda: None)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    result = youtube_tool.run_youtube_lookup("dQw4w9WgXcQ")
    assert "[EXTERNAL]" in result
    assert "ERROR" in result


def test_youtube_happy_path():
    from echo.api.tools.youtube_tool import run_youtube_lookup

    mock_api_response = {
        "items": [{
            "snippet": {
                "title": "Test Video",
                "channelTitle": "Test Channel",
                "description": "A test description",
                "tags": ["tag1", "tag2"],
                "publishedAt": "2020-01-01T00:00:00Z",
            },
            "contentDetails": {"duration": "PT10M30S"},
            "statistics": {"viewCount": "1000000"},
        }]
    }

    with patch("googleapiclient.discovery.build") as mock_build:
        mock_yt = MagicMock()
        mock_build.return_value = mock_yt
        mock_yt.videos.return_value.list.return_value.execute.return_value = mock_api_response

        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "fake_key"}):
            result = run_youtube_lookup("dQw4w9WgXcQ")

    assert result.startswith("[EXTERNAL]")
    assert "Test Video" in result
    assert "Test Channel" in result


def test_youtube_video_not_found():
    from echo.api.tools.youtube_tool import run_youtube_lookup

    with patch("googleapiclient.discovery.build") as mock_build:
        mock_yt = MagicMock()
        mock_build.return_value = mock_yt
        mock_yt.videos.return_value.list.return_value.execute.return_value = {"items": []}

        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "fake_key"}):
            result = run_youtube_lookup("NOTAVALIDID")

    assert "[EXTERNAL]" in result
    assert "no video found" in result.lower() or "not found" in result.lower() or "ERROR" in result


# ── execute_python sandbox gate ───────────────────────────────────────────────

def test_execute_python_sandbox_disabled():
    from echo.api.tools.python_tool import execute_python
    with patch.dict(os.environ, {"UNSAFE_PYTHON_SANDBOX": "false"}):
        result = execute_python("print('hello')")
    assert "[RAW-COMPUTED] ERROR" in result
    assert "disabled" in result.lower()


def test_execute_python_sandbox_enabled():
    from echo.api.tools.python_tool import execute_python
    with patch.dict(os.environ, {"UNSAFE_PYTHON_SANDBOX": "true"}):
        result = execute_python("print('hello world')")
    assert "hello world" in result


def test_execute_python_scipy_available():
    from echo.api.tools.python_tool import execute_python
    with patch.dict(os.environ, {"UNSAFE_PYTHON_SANDBOX": "true"}):
        result = execute_python("import scipy; print('scipy ok')")
    assert "scipy ok" in result


def test_execute_python_sklearn_available():
    from echo.api.tools.python_tool import execute_python
    with patch.dict(os.environ, {"UNSAFE_PYTHON_SANDBOX": "true"}):
        result = execute_python("from sklearn.cluster import KMeans; print('sklearn ok')")
    assert "sklearn ok" in result


def test_execute_python_statsmodels_available():
    from echo.api.tools.python_tool import execute_python
    with patch.dict(os.environ, {"UNSAFE_PYTHON_SANDBOX": "true"}):
        result = execute_python("import statsmodels.api as sm; print('sm ok')")
    assert "sm ok" in result


# ── web_search tool ───────────────────────────────────────────────────────────

def test_web_search_rate_limit_blocks_sixth_call():
    from echo.api.tools.web_search_tool import run_web_search, _RATE_LIMIT
    state = {"web_search_count": _RATE_LIMIT}
    result = run_web_search("anything", k=3, session_state=state)
    assert "BLOCKED" in result
    assert "web_search_count" not in result or state["web_search_count"] == _RATE_LIMIT


def test_web_search_happy_path():
    from echo.api.tools.web_search_tool import run_web_search
    mock_results = [
        {"title": "Result 1", "body": "Snippet about topic", "href": "https://example.com/1"},
        {"title": "Result 2", "body": "Another snippet",    "href": "https://example.com/2"},
    ]
    state: dict = {}
    with patch("duckduckgo_search.DDGS") as mock_ddgs:
        mock_ddgs.return_value.text.return_value = mock_results
        result = run_web_search("test query", k=2, session_state=state)
    assert "[EXTERNAL]" in result
    assert "Result 1" in result
    assert state["web_search_count"] == 1


def test_web_search_empty_results_flags_rate_limit():
    from echo.api.tools.web_search_tool import run_web_search
    state: dict = {}
    with patch("duckduckgo_search.DDGS") as mock_ddgs:
        mock_ddgs.return_value.text.return_value = []
        result = run_web_search("obscure query", k=3, session_state=state)
    assert "rate-limiting" in result.lower() or "no results" in result.lower()
    assert state["web_search_count"] == 1


def test_web_search_exception_increments_and_returns_error():
    from echo.api.tools.web_search_tool import run_web_search
    state: dict = {}
    with patch("duckduckgo_search.DDGS") as mock_ddgs:
        mock_ddgs.return_value.text.side_effect = RuntimeError("network failure")
        result = run_web_search("query", k=3, session_state=state)
    assert "[EXTERNAL]" in result
    assert "ERROR" in result
    assert state["web_search_count"] == 1


def test_dispatch_web_search_routing():
    from echo.api.tools import dispatch
    state: dict = {}
    with patch("duckduckgo_search.DDGS") as mock_ddgs:
        mock_ddgs.return_value.text.return_value = [
            {"title": "T", "body": "B", "href": "https://x.com"}
        ]
        result = dispatch("web_search", {"query": "hello", "k": 1}, phase=1, session_state=state)
    assert "[EXTERNAL]" in result


# ── dispatch() session_state threading ───────────────────────────────────────

def test_dispatch_passes_session_state():
    """dispatch() must accept session_state without raising."""
    from echo.api.tools import dispatch
    state: dict = {}
    # run_sql is always available in phase 1; this just checks the call signature
    result = dispatch("run_sql", {"query": "SELECT 1"}, phase=1, session_state=state)
    assert result  # any non-exception result is fine


# ── Phase-1 narrative blindness (the reflections block) ───────────────────────
# CLAUDE.md gotcha: Agent Phase 1 (rounds 1-10) blocks the reflections lancedb
# table in BOTH vector_search dispatch AND run_sql. This is intentional — Phase 1
# hypotheses must form from raw behavioral data only, never LLM-generated narrative.
# These guard that the block fires in Phase 1 and lifts in Phase 2, and crucially
# that the underlying tool is NOT even called when blocked.

def test_phase1_blocks_vector_search_reflections_without_calling_tool(monkeypatch):
    import echo.api.tools as tools
    called = {"n": 0}
    monkeypatch.setattr(tools, "vector_search", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "REAL")
    result = tools.dispatch("vector_search", {"table": "reflections", "query": "x"}, phase=1)
    assert "BLOCKED" in result and "NARRATIVE" in result
    assert called["n"] == 0, "the real vector_search must not run when blocked in Phase 1"


def test_phase1_blocks_run_sql_touching_reflections_without_calling_tool(monkeypatch):
    import echo.api.tools as tools
    called = {"n": 0}
    monkeypatch.setattr(tools, "run_sql", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "REAL")
    result = tools.dispatch("run_sql", {"query": "SELECT reflection FROM reflections LIMIT 1"}, phase=1)
    assert "BLOCKED" in result
    assert called["n"] == 0, "the real run_sql must not run when reflections is touched in Phase 1"


def test_phase1_allows_vector_search_on_raw_tables(monkeypatch):
    """The block is narrow: only the reflections table. Raw tables pass through."""
    import echo.api.tools as tools
    monkeypatch.setattr(tools, "vector_search", lambda *a, **k: "[SEMANTIC-RAW] passthrough")
    result = tools.dispatch("vector_search", {"table": "videos", "query": "x"}, phase=1)
    assert "BLOCKED" not in result
    assert "passthrough" in result


def test_phase2_lifts_reflections_block(monkeypatch):
    """In Phase 2 the same calls pass through to the real tools — block is gone."""
    import echo.api.tools as tools
    monkeypatch.setattr(tools, "vector_search", lambda *a, **k: "[NARRATIVE] reflections result")
    monkeypatch.setattr(tools, "run_sql", lambda *a, **k: "[RAW-SQL] reflections rows")

    vs = tools.dispatch("vector_search", {"table": "reflections", "query": "x"}, phase=2)
    sql = tools.dispatch("run_sql", {"query": "SELECT reflection FROM reflections"}, phase=2)
    assert "BLOCKED" not in vs and "reflections result" in vs
    assert "BLOCKED" not in sql and "reflections rows" in sql
