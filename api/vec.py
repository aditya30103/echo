"""lancedb connection and semantic search helpers."""

import sys
from pathlib import Path

import lancedb

BASE = Path(__file__).parent.parent
LANCEDB_PATH = BASE / "lancedb"

_ldb = None


def get_ldb() -> lancedb.DBConnection:
    global _ldb
    if _ldb is None:
        if not LANCEDB_PATH.exists():
            print("ERROR: lancedb/ not found. Run embed.py first.", file=sys.stderr)
        _ldb = lancedb.connect(str(LANCEDB_PATH))
    return _ldb


def embed_query(query: str) -> list[float]:
    """Embed a query string using the configured provider (OpenAI or OpenRouter)."""
    # Import here so FastAPI startup doesn't fail if keys aren't set yet.
    import os
    sys.path.insert(0, str(BASE))
    from embed_common import load_env, get_embed_client
    load_env()
    client, model = get_embed_client()
    resp = client.embeddings.create(model=model, input=[query])
    return resp.data[0].embedding


def search_table(
    table_name: str,
    vector: list[float],
    top: int = 10,
) -> list[dict]:
    """Return top-N cosine-nearest rows from a lancedb table."""
    ldb = get_ldb()
    available = ldb.list_tables().tables
    if table_name not in available:
        return []
    table = ldb.open_table(table_name)
    rows = (
        table.search(vector)
        .metric("cosine")
        .limit(top)
        .to_list()
    )
    # Convert to plain dicts and add similarity score (1 - cosine distance)
    results = []
    for r in rows:
        d = {k: v for k, v in r.items() if k != "vector"}
        d["similarity"] = round(1.0 - float(r["_distance"]), 4)
        d.pop("_distance", None)
        results.append(d)
    return results
