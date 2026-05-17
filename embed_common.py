"""DEPRECATED legacy shim. Re-exports from echo.config for callsites that
haven't migrated yet (currently 4 files in api/: vec.py, observability.py,
llm.py, tools/youtube_tool.py).

This file is deleted at the end of the api/ migration step (P2.X), once
every `from embed_common import ...` has been replaced with
`from echo.config import ...`.

DO NOT add new imports to this file. Use `from echo.config import ...` directly.
"""

from echo.config import (
    ALL_TABLES,
    get_embed_client,
    load_env,
)

__all__ = ["ALL_TABLES", "get_embed_client", "load_env"]
