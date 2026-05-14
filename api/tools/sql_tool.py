"""run_sql tool — SELECT-only access to echo.db."""

import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "echo.db"

_SELECT_RE = re.compile(r'^\s*SELECT\b', re.IGNORECASE)
_ROW_LIMIT  = 200
_CHAR_LIMIT = 6000


def run_sql(query: str) -> str:
    """Execute a SELECT query against echo.db. Returns [RAW-SQL] tagged string."""
    if not _SELECT_RE.match(query):
        return "[RAW-SQL] ERROR: Only SELECT queries are permitted."
    try:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(query)
        rows = cur.fetchmany(_ROW_LIMIT)
        conn.close()
        if not rows:
            return "[RAW-SQL] (no rows returned)"
        dicts = [dict(r) for r in rows]
        text = "\n".join(str(d) for d in dicts)
        truncated = len(dicts) == _ROW_LIMIT
        if len(text) > _CHAR_LIMIT:
            text = text[:_CHAR_LIMIT] + "\n... [output truncated]"
        suffix = f"\n[{len(dicts)} rows" + (" — may be more, hit row limit]" if truncated else "]")
        return f"[RAW-SQL]\n{text}{suffix}"
    except Exception as e:
        return f"[RAW-SQL] ERROR: {e}"
