"""Tests for Sprint 3 tools: run_pelt, run_clustering, run_youtube_lookup, execute_python."""

import os
import json
import pytest
from unittest.mock import patch, MagicMock


# ── run_pelt ──────────────────────────────────────────────────────────────────

def test_pelt_invalid_table():
    from api.tools.pelt_tool import run_pelt
    result = run_pelt(table="nonexistent_table", ts_col="watched_at")
    assert "ERROR" in result or "error" in result.lower()


def test_pelt_invalid_freq():
    from api.tools.pelt_tool import run_pelt
    result = run_pelt(table="watches", ts_col="watched_at", freq="INVALID")
    assert "ERROR" in result or "error" in result.lower()


def test_pelt_happy_path():
    from api.tools.pelt_tool import run_pelt
    result = run_pelt(table="watches", ts_col="watched_at", value_col="*", freq="W", penalty=2.0)
    assert result.startswith("[RAW-COMPUTED]")
    data = json.loads(result[len("[RAW-COMPUTED] "):])
    assert "breakpoint_dates" in data
    assert "segments" in data
    assert isinstance(data["segments"], list)


# ── run_clustering ─────────────────────────────────────────────────────────────

def test_clustering_invalid_table():
    from api.tools.clustering_tool import run_clustering
    result = run_clustering(table="nonexistent_table")
    assert "ERROR" in result


def test_clustering_n_clusters_below_min():
    from api.tools.clustering_tool import run_clustering
    result = run_clustering(table="videos", n_clusters=1)
    assert "ERROR" in result


def test_clustering_n_clusters_exceeds_rows():
    from api.tools.clustering_tool import run_clustering
    # n_clusters=9999 will always exceed actual row count in any realistic table
    result = run_clustering(table="videos", n_clusters=9999)
    assert "ERROR" in result


def test_clustering_happy_path():
    from api.tools.clustering_tool import run_clustering
    result = run_clustering(table="videos", n_clusters=3)
    assert result.startswith("[RAW-COMPUTED]")
    data = json.loads(result[len("[RAW-COMPUTED] "):])
    assert "silhouette_score" in data
    assert "clusters" in data
    assert len(data["clusters"]) == 3


# ── run_youtube_lookup ────────────────────────────────────────────────────────

def test_youtube_missing_api_key(monkeypatch):
    from api.tools import youtube_tool

    # `run_youtube_lookup` calls `_load_env` which reads .env via echo.config
    # and may re-populate YOUTUBE_API_KEY from the file on the dev's host.
    # Stub it out so we control exactly what the tool sees.
    monkeypatch.setattr(youtube_tool, "_load_env", lambda: None)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    result = youtube_tool.run_youtube_lookup("dQw4w9WgXcQ")
    assert "[EXTERNAL]" in result
    assert "ERROR" in result


def test_youtube_happy_path():
    from api.tools.youtube_tool import run_youtube_lookup

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
    from api.tools.youtube_tool import run_youtube_lookup

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
    from api.tools.python_tool import execute_python
    with patch.dict(os.environ, {"UNSAFE_PYTHON_SANDBOX": "false"}):
        result = execute_python("print('hello')")
    assert "[RAW-COMPUTED] ERROR" in result
    assert "disabled" in result.lower()


def test_execute_python_sandbox_enabled():
    from api.tools.python_tool import execute_python
    with patch.dict(os.environ, {"UNSAFE_PYTHON_SANDBOX": "true"}):
        result = execute_python("print('hello world')")
    assert "hello world" in result


def test_execute_python_scipy_available():
    from api.tools.python_tool import execute_python
    with patch.dict(os.environ, {"UNSAFE_PYTHON_SANDBOX": "true"}):
        result = execute_python("import scipy; print('scipy ok')")
    assert "scipy ok" in result


def test_execute_python_sklearn_available():
    from api.tools.python_tool import execute_python
    with patch.dict(os.environ, {"UNSAFE_PYTHON_SANDBOX": "true"}):
        result = execute_python("from sklearn.cluster import KMeans; print('sklearn ok')")
    assert "sklearn ok" in result


def test_execute_python_statsmodels_available():
    from api.tools.python_tool import execute_python
    with patch.dict(os.environ, {"UNSAFE_PYTHON_SANDBOX": "true"}):
        result = execute_python("import statsmodels.api as sm; print('sm ok')")
    assert "sm ok" in result


# ── web_search tool ───────────────────────────────────────────────────────────

def test_web_search_rate_limit_blocks_sixth_call():
    from api.tools.web_search_tool import run_web_search, _RATE_LIMIT
    state = {"web_search_count": _RATE_LIMIT}
    result = run_web_search("anything", k=3, session_state=state)
    assert "BLOCKED" in result
    assert "web_search_count" not in result or state["web_search_count"] == _RATE_LIMIT


def test_web_search_happy_path():
    from api.tools.web_search_tool import run_web_search
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
    from api.tools.web_search_tool import run_web_search
    state: dict = {}
    with patch("duckduckgo_search.DDGS") as mock_ddgs:
        mock_ddgs.return_value.text.return_value = []
        result = run_web_search("obscure query", k=3, session_state=state)
    assert "rate-limiting" in result.lower() or "no results" in result.lower()
    assert state["web_search_count"] == 1


def test_web_search_exception_increments_and_returns_error():
    from api.tools.web_search_tool import run_web_search
    state: dict = {}
    with patch("duckduckgo_search.DDGS") as mock_ddgs:
        mock_ddgs.return_value.text.side_effect = RuntimeError("network failure")
        result = run_web_search("query", k=3, session_state=state)
    assert "[EXTERNAL]" in result
    assert "ERROR" in result
    assert state["web_search_count"] == 1


def test_dispatch_web_search_routing():
    from api.tools import dispatch
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
    from api.tools import dispatch
    state: dict = {}
    # run_sql is always available in phase 1; this just checks the call signature
    result = dispatch("run_sql", {"query": "SELECT 1"}, phase=1, session_state=state)
    assert result  # any non-exception result is fine
