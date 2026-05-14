"""execute_python tool — sandboxed Python with sqlite3/pandas/numpy access."""

import subprocess
import sys
import textwrap
from pathlib import Path

_DB_PATH  = str(Path(__file__).parent.parent.parent / "echo.db")
_TIMEOUT  = 30   # seconds; kills runaway loops
_CHAR_LIMIT = 8000

# Injected at top of every execution so the model's code can use db / pd / np directly.
_PREAMBLE = textwrap.dedent("""\
    import os, sqlite3, json, warnings
    warnings.filterwarnings("ignore")
    import pandas as pd
    import numpy as np
    DB_PATH = {db_path!r}
    _conn = sqlite3.connect(DB_PATH)
    _conn.row_factory = sqlite3.Row

    def sql(q):
        return pd.read_sql_query(q, _conn)
""")


def execute_python(code: str) -> str:
    """Run code in a subprocess. Returns [RAW-COMPUTED] tagged string."""
    full = _PREAMBLE.format(db_path=_DB_PATH) + "\n" + code
    try:
        result = subprocess.run(
            [sys.executable, "-c", full],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        output = result.stdout
        if result.returncode != 0 and result.stderr:
            output += f"\nERROR: {result.stderr[:800]}"
        if not output.strip():
            output = "(no output — use print() to surface results)"
        if len(output) > _CHAR_LIMIT:
            output = output[:_CHAR_LIMIT] + "\n... [output truncated]"
        return f"[RAW-COMPUTED]\n{output}"
    except subprocess.TimeoutExpired:
        return f"[RAW-COMPUTED] ERROR: Timed out after {_TIMEOUT}s. Simplify the computation."
    except Exception as e:
        return f"[RAW-COMPUTED] ERROR: {e}"
