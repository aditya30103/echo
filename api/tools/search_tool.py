"""vector_search tool — semantic search in lancedb."""

from api.vec import embed_query, search_table

_RAW_TABLES       = {"videos", "searches", "google_searches"}
_NARRATIVE_TABLES = {"reflections"}


def vector_search(query: str, table: str, limit: int = 5) -> str:
    """Semantic search in lancedb. Returns source-tagged string."""
    if table in _NARRATIVE_TABLES:
        tag = "[NARRATIVE]"
    elif table in _RAW_TABLES:
        tag = "[SEMANTIC-RAW]"
    else:
        return (
            f"[SEMANTIC-RAW] ERROR: Unknown table {table!r}. "
            f"Valid: {sorted(_RAW_TABLES | _NARRATIVE_TABLES)}"
        )

    try:
        vector = embed_query(query)
        rows   = search_table(table, vector, top=limit)
    except Exception as e:
        return f"{tag} ERROR: {e}"

    if not rows:
        return f"{tag} No results in {table!r}."

    lines = []
    for r in rows:
        sim = f"{r.get('similarity', 0):.0%}"
        if table == "reflections":
            text = (r.get("text") or "")[:200].replace("\n", " ")
            span = f"{(r.get('start_at') or '')[:7]}–{(r.get('end_at') or '')[:7]}"
            lines.append(f"  Ch{r.get('chapter_id')} {span} [{sim}]: {text}")
        elif table == "videos":
            lines.append(
                f"  [{sim}] {r.get('title') or r.get('video_id')} "
                f"— {r.get('channel')} (watched {r.get('watch_count', '?')}×)"
            )
        else:  # searches / google_searches
            span = f"{(r.get('first_seen') or '')[:7]}–{(r.get('last_seen') or '')[:7]}"
            lines.append(f"  [{sim}] \"{r.get('query')}\" — {r.get('count')}× {span}")

    return f"{tag} table={table}\n" + "\n".join(lines)
