"""Guard: the FastAPI backend must import as part of the installed `echo` package,
from ANY working directory — not only when the process happens to launch from the
repo root.

Why this exists
---------------
Before the api/ move, the backend lived at the repo root (`api/`), outside the wheel.
`echo serve` did `from api.main import app`, which resolved ONLY because the process
was launched from the repo root (cwd on sys.path). A `pip install`ed user running
`echo serve` from anywhere else hit `ModuleNotFoundError: No module named 'api'`.
The whole test suite missed it because pytest also runs from the repo root.

This test reproduces the packaged-user's view: it spawns a fresh interpreter with a
foreign cwd and PYTHONPATH stripped, so the repo root is NOT on sys.path. If
`echo.api.main` imports there, the backend genuinely ships inside the package.

This is the fast (~1-2s) regression guard. The companion full wheel-build smoke
(build → clean venv → boot `echo serve`) runs in CI and additionally catches
packaging-metadata regressions (e.g. ui/dist not force-included).
"""

from __future__ import annotations

import os
import subprocess
import sys


def _foreign_env() -> dict[str, str]:
    """Copy of the environment with PYTHONPATH removed.

    The editable/installed `echo` package is found via its site-packages finder,
    not PYTHONPATH — so dropping PYTHONPATH keeps the install discoverable while
    guaranteeing the repo root isn't smuggled onto sys.path through it.
    """
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return env


def test_api_app_imports_from_foreign_cwd(tmp_path):
    """`import echo.api.main` must succeed from a cwd outside the repo.

    Asserts the app object exists and a known route is registered — which forces
    every router (db, llm, vec, tools, compressors, observability) to import too,
    so a half-moved module surfaces here instead of at `echo serve` time.
    """
    code = (
        "import echo.api.main as m; "
        "assert m.app is not None, 'app missing'; "
        "paths = {getattr(r, 'path', None) for r in m.app.routes}; "
        "assert '/api/health' in paths, f'health route missing: {sorted(p for p in paths if p)}'; "
        "print('PACKAGED_IMPORT_OK')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,            # foreign cwd: the repo root is not here
        env=_foreign_env(),      # repo root not on sys.path via PYTHONPATH either
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "echo.api.main failed to import from a foreign cwd — the backend is not "
        f"shipping inside the package (the api/ packaging regression).\n"
        f"cwd={tmp_path}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "PACKAGED_IMPORT_OK" in result.stdout
