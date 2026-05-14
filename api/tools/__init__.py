"""Tool registry for Echo Speaks agent — v3 toolkit."""

import json

from api.tools.sql_tool        import run_sql
from api.tools.python_tool     import execute_python
from api.tools.search_tool     import vector_search
from api.tools.pelt_tool       import run_pelt
from api.tools.clustering_tool import run_clustering
from api.tools.youtube_tool    import run_youtube_lookup

# Tables whose content is LLM-generated narrative — blocked in Phase 1.
_NARRATIVE_VECTOR_TABLES = {"reflections"}


def _is_narrative(tool: str, args: dict) -> bool:
    if tool == "vector_search" and args.get("table") in _NARRATIVE_VECTOR_TABLES:
        return True
    return False


def _is_sql_reflections(tool: str, args: dict) -> bool:
    """Detect run_sql queries that touch the reflections table directly."""
    if tool != "run_sql":
        return False
    query = args.get("query", "").lower()
    return "reflections" in query


def dispatch(tool: str, args: dict, phase: int, session_state: dict | None = None) -> str:
    """Call the named tool with args. Enforces phase rules at the dispatch layer.

    session_state: mutable dict created per _react_loop() call, shared across all
    dispatch() calls in that session. Used for per-session rate limiting (e.g. web_search).
    """
    if session_state is None:
        session_state = {}

    # Phase 1: block narrative vector search
    if phase == 1 and _is_narrative(tool, args):
        return (
            f"[NARRATIVE] BLOCKED: vector_search with table='reflections' "
            "is not available in Phase 1. Use run_sql, execute_python, or "
            "vector_search on videos/searches/google_searches instead."
        )

    # Phase 1: block direct SQL access to the reflections table
    if phase == 1 and _is_sql_reflections(tool, args):
        return (
            "[NARRATIVE] BLOCKED: The reflections table is not available in Phase 1. "
            "Query other tables instead. Reflections are LLM-generated narratives "
            "and must not anchor Phase 1 hypotheses."
        )

    if tool == "run_sql":
        return run_sql(args.get("query", ""))

    if tool == "execute_python":
        return execute_python(args.get("code", ""))

    if tool == "vector_search":
        return vector_search(
            args.get("query", ""),
            args.get("table", ""),
            int(args.get("limit", 5)),
        )

    if tool == "run_pelt":
        return run_pelt(
            table=args.get("table", ""),
            ts_col=args.get("ts_col", ""),
            value_col=args.get("value_col", "*"),
            freq=str(args.get("freq", "W")),
            penalty=float(args.get("penalty", 2.0)),
        )

    if tool == "run_clustering":
        return run_clustering(
            table=str(args.get("table", "")),
            n_clusters=int(args.get("n_clusters", 5)),
        )

    if tool == "youtube_lookup":
        return run_youtube_lookup(str(args.get("video_id", "")))

    return (
        f"[ERROR] Unknown tool: '{tool}'. Valid tools: "
        "run_sql, execute_python, vector_search, run_pelt, run_clustering, "
        "youtube_lookup, finish."
    )


def tool_descriptions(narrative_blind: bool = True) -> str:
    base = """\
- run_sql(query: str)
    Execute a SELECT query against echo.db. Returns rows. Only SELECT is permitted.
    Schema inspection: SELECT name, type FROM pragma_table_info('watches')
    Example: run_sql("SELECT COUNT(*) n FROM watches WHERE datetime(watched_at, '+330 minutes') LIKE '%-23%'")

- execute_python(code: str)
    Run Python code. Available: db (sqlite3 connection), sql(q) (returns DataFrame),
    pd, np, scipy, scipy_stats, sm (statsmodels), KMeans, StandardScaler, silhouette_score.
    Use print() to surface results. Timeout: 30s.
    Example: execute_python("df = sql('SELECT ...'); print(df.describe())")

- vector_search(query: str, table: str, limit: int = 5)
    Semantic search. RAW tables: videos, searches, google_searches. NARRATIVE: reflections (Phase 2 only).
    Example: vector_search("philosophy content", "videos", 5)

- run_pelt(table: str, ts_col: str, value_col: str = "*", freq: str = "W", penalty: float = 2.0)
    PELT changepoint detection on any time series in echo.db.
    value_col="*" counts rows per period. freq="W" (weekly) or "D" (daily).
    Returns breakpoint dates and per-segment means.
    Example: run_pelt("watches", "watched_at", "*", "W", 2.0)

- run_clustering(table: str, n_clusters: int = 5)
    k-means clustering on lancedb embedding vectors. table: videos | searches | google_searches.
    Returns cluster sizes, nearest examples per centroid, and silhouette score.
    Use run_sql to characterise clusters by metadata after clustering.
    Example: run_clustering("videos", 6)

- youtube_lookup(video_id: str)
    Look up a YouTube video via Data API. Returns title, channel, tags, description,
    view count, duration. Use to add external context to an anomalous video.
    Source tag: [EXTERNAL]. Quota-aware (9,000 units/day limit).
    Example: youtube_lookup("dQw4w9WgXcQ")"""

    narrative_tools = """\

- vector_search with table="reflections"
    [NARRATIVE] Semantic search over chapter arc narratives. Use only to verify Phase 1 findings."""

    finish_tool = """\

- finish(findings: list, side_insights: list)
    End the loop and return results.
    findings: [{"claim": str, "evidence": str, "source_tag": "RAW-SQL|RAW-COMPUTED|SEMANTIC-RAW|EXTERNAL", "confidence": "high|medium|low"}]
    EXTERNAL findings (youtube_lookup): set confidence="medium"; they appear as supplementary in the response.
    side_insights: [str]  — smaller observations worth noting"""

    return base + ("" if narrative_blind else narrative_tools) + finish_tool
