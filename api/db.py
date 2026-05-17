"""SQLite connection for the Echo API."""

import sqlite3
import sqlite_utils

from echo.data.paths import get_db_path

DB_PATH = get_db_path()

_db: sqlite_utils.Database | None = None


def get_db() -> sqlite_utils.Database:
    global _db
    if _db is None:
        # check_same_thread=False: FastAPI uses a thread pool; pass to sqlite3 directly.
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _db = sqlite_utils.Database(conn)
    return _db
