"""SQLite connection for the Echo API."""

import sqlite3
from pathlib import Path
import sqlite_utils

DB_PATH = Path(__file__).parent.parent / "echo.db"

_db: sqlite_utils.Database | None = None


def get_db() -> sqlite_utils.Database:
    global _db
    if _db is None:
        # check_same_thread=False: FastAPI uses a thread pool; pass to sqlite3 directly.
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _db = sqlite_utils.Database(conn)
    return _db
