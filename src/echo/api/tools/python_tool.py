"""execute_python tool — sandboxed Python with sqlite3/pandas/numpy/scipy/sklearn access."""

import os
import subprocess
import sys
import textwrap

from echo.data.paths import get_db_path

_DB_PATH     = str(get_db_path())
_TIMEOUT     = 30     # seconds; kills runaway loops
_STDOUT_CAP  = 10000  # chars; printing full DataFrames wastes context window
_STDERR_CAP  = 3000   # chars; scientific library tracebacks can reach 2,000+ chars

# Injected at top of every execution so the model's code can use db / pd / np directly.
_PREAMBLE = textwrap.dedent("""\
    import os, sqlite3, json, warnings
    warnings.filterwarnings("ignore")
    import pandas as pd
    import numpy as np
    import scipy
    from scipy import stats as scipy_stats
    import statsmodels.api as sm
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import silhouette_score
    DB_PATH = {db_path!r}
    _conn = sqlite3.connect(DB_PATH)
    _conn.row_factory = sqlite3.Row

    def sql(q):
        return pd.read_sql_query(q, _conn)
""")


def execute_python(code: str) -> str:
    """Run code in a subprocess. Returns [RAW-COMPUTED] tagged string.

    Requires UNSAFE_PYTHON_SANDBOX=true in environment (defaults to true for local dev).
    Set UNSAFE_PYTHON_SANDBOX=false to disable for public deployments.
    """
    # Gate: explicit opt-out for public deployments; defaults to enabled for local use.
    if os.environ.get("UNSAFE_PYTHON_SANDBOX", "true").lower() == "false":
        return (
            "[RAW-COMPUTED] ERROR: Python sandbox is disabled. "
            "Set UNSAFE_PYTHON_SANDBOX=true in .env to enable execute_python."
        )

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
            output += f"\nERROR: {result.stderr[:_STDERR_CAP]}"
        if not output.strip():
            output = "(no output — use print() to surface results)"
        if len(output) > _STDOUT_CAP:
            output = output[:_STDOUT_CAP] + "\n... [output truncated — avoid printing full DataFrames]"
        return f"[RAW-COMPUTED]\n{output}"
    except subprocess.TimeoutExpired:
        return f"[RAW-COMPUTED] ERROR: Timed out after {_TIMEOUT}s. Simplify the computation."
    except Exception as e:
        return f"[RAW-COMPUTED] ERROR: {e}"
