"""Pytest configuration.

Until proper fixture-based integration tests land (Session 2 item: per-step
smoke tests against tests/fixtures/sample-takeout.zip), two tests in
test_tools.py call into the agent toolkit against the developer's actual
echo.db / lancedb at the repo root:

  - test_tools::test_pelt_happy_path       (needs `watches` table)
  - test_tools::test_clustering_happy_path (needs `videos` lancedb table)

Pre-packaging, those modules hardcoded
`Path(__file__).parent.parent.parent / "echo.db"` which happened to resolve
to the repo root. Post-packaging, they read from get_db_path() which
defaults to `~/.echo/echo.db` (the new home).

This conftest.py points `ECHO_DATA_DIR` at the repo root for the test
run so the legacy behavior is preserved. Once those tests are rewritten
to use a sample-takeout fixture (per the packaging design doc), this file
can shrink to whatever the fixture setup needs (likely a tmp_path-based
data_dir per-test).
"""

import os
from pathlib import Path

# tests/conftest.py -> tests/.. = repo root
_REPO_ROOT = Path(__file__).parent.parent

# setdefault: respect any explicit ECHO_DATA_DIR a developer set in the shell.
os.environ.setdefault("ECHO_DATA_DIR", str(_REPO_ROOT))
