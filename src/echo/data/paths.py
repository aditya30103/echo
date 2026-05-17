"""Echo data directory resolution.

Default: ~/.echo/  (Windows: %USERPROFILE%\\.echo\\)
Override: set ECHO_DATA_DIR env var to any path.

Holds: echo.db, echo.db-shm, echo.db-wal, lancedb/, config.toml,
       private/annotations.yaml, .env (secrets).
"""

import os
from pathlib import Path


def get_data_dir() -> Path:
    """Return the resolved Echo data directory as a Path.

    Honors $ECHO_DATA_DIR if set (expanded for ~ and env vars).
    Defaults to ~/.echo/.

    Does NOT create the directory — callers that need it should
    `path.mkdir(parents=True, exist_ok=True)` after calling.
    """
    override = os.environ.get("ECHO_DATA_DIR")
    if override:
        return Path(os.path.expandvars(override)).expanduser()
    return Path.home() / ".echo"


def get_db_path() -> Path:
    """Path to echo.db inside the data dir."""
    return get_data_dir() / "echo.db"


def get_lancedb_path() -> Path:
    """Path to lancedb/ inside the data dir."""
    return get_data_dir() / "lancedb"


def get_config_path() -> Path:
    """Path to config.toml inside the data dir."""
    return get_data_dir() / "config.toml"


def get_env_path() -> Path:
    """Path to .env (secrets) inside the data dir.

    Note: legacy callers still read .env from the project root. The
    api/ migration step (Step P2.X) flips them to this location.
    """
    return get_data_dir() / ".env"


def get_private_dir() -> Path:
    """Path to private/ (life context annotations) inside the data dir."""
    return get_data_dir() / "private"
