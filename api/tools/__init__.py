"""Tool registry for Echo Speaks agent."""

from api.tools.sql_tool     import run_sql
from api.tools.python_tool  import execute_python
from api.tools.search_tool  import vector_search, get_chapter_context

# Tools that return [NARRATIVE] tagged observations — blocked in Phase 1.
_NARRATIVE_TOOL_COMBOS: set[tuple] = set()  # checked at dispatch time via _is_narrative()


def _is_narrative(tool: str, args: dict) -> bool:
    if tool == "get_chapter_context":
        return True
    if tool == "vector_search" and args.get("table") == "reflections":
        return True
    return False


def dispatch(tool: str, args: dict, phase: int) -> str:
    """Call the named tool with args. Enforces phase rules at the dispatch layer."""
    if phase == 1 and _is_narrative(tool, args):
        return (
            f"[NARRATIVE] BLOCKED: '{tool}' with table='reflections' or get_chapter_context "
            "are not available in Phase 1. Use run_sql, execute_python, or vector_search on "
            "videos/searches/google_searches tables instead."
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

    if tool == "get_chapter_context":
        return get_chapter_context(int(args.get("chapter_id", 0)))

    return f"[ERROR] Unknown tool: '{tool}'. Valid tools: run_sql, execute_python, vector_search, get_chapter_context, finish."


def tool_descriptions(narrative_blind: bool = True) -> str:
    base = """\
- run_sql(query: str)
    Execute a SELECT query against echo.db. Returns rows. Only SELECT is permitted.
    Schema inspection: SELECT name, type FROM pragma_table_info('watches')
    Example: run_sql("SELECT COUNT(*) n FROM watches WHERE datetime(watched_at, '+330 minutes') LIKE '%-23%'")

- execute_python(code: str)
    Run Python code. Variables available: db (sqlite3 connection), sql(q) (returns DataFrame), pd, np.
    Use print() to surface results. Timeout: 30s.
    Example: execute_python("df = sql('SELECT ...'); print(df.describe())")

- vector_search(query: str, table: str, limit: int = 5)
    Semantic search. RAW tables: videos, searches, google_searches. NARRATIVE table: reflections.
    Example: vector_search("philosophy content", "videos", 5)"""

    narrative_tools = """\

- get_chapter_context(chapter_id: int)
    [NARRATIVE] Return fingerprint + reflection for one chapter. Use only to verify Phase 1 findings.
    Example: get_chapter_context(12)

- vector_search with table="reflections"
    [NARRATIVE] Semantic search over chapter arc narratives. Use only to verify Phase 1 findings."""

    finish_tool = """\

- finish(findings: list, side_insights: list)
    End the loop and return results.
    findings: [{"claim": str, "evidence": str, "source_tag": "RAW-SQL|RAW-COMPUTED|SEMANTIC-RAW", "confidence": "high|medium|low"}]
    side_insights: [str]  — smaller observations worth noting"""

    return base + ("" if narrative_blind else narrative_tools) + finish_tool
