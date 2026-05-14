"""vector_search and get_chapter_context tools."""

import sqlite3
from pathlib import Path

from api.vec import embed_query, search_table

DB_PATH = Path(__file__).parent.parent.parent / "echo.db"

_RAW_TABLES       = {"videos", "searches", "google_searches"}
_NARRATIVE_TABLES = {"reflections"}


def vector_search(query: str, table: str, limit: int = 5) -> str:
    """Semantic search in lancedb. Returns source-tagged string."""
    if table in _NARRATIVE_TABLES:
        tag = "[NARRATIVE]"
    elif table in _RAW_TABLES:
        tag = "[SEMANTIC-RAW]"
    else:
        return f"[SEMANTIC-RAW] ERROR: Unknown table '{table}'. Valid: {sorted(_RAW_TABLES | _NARRATIVE_TABLES)}"

    try:
        vector = embed_query(query)
        rows = search_table(table, vector, top=limit)
    except Exception as e:
        return f"{tag} ERROR: {e}"

    if not rows:
        return f"{tag} No results in '{table}'."

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


def get_chapter_context(chapter_id: int) -> str:
    """Return fingerprint + reflection for one chapter. [NARRATIVE] tagged."""
    try:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT c.id, c.label, c.start_at, c.end_at, c.watch_count,
                   cf.night_ratio, cf.long_form_ratio, cf.shorts_ratio,
                   cf.channel_density_score, cf.modal_hour, cf.median_duration_seconds,
                   r.text AS reflection
            FROM chapters c
            LEFT JOIN chapter_fingerprints cf ON cf.chapter_id = c.id
            LEFT JOIN reflections r ON r.chapter_id = c.id
            WHERE c.id = ?
            """,
            [chapter_id],
        ).fetchone()
        conn.close()
        if not row:
            return f"[NARRATIVE] ERROR: Chapter {chapter_id} not found."
        d = dict(row)
        reflection = (d.get("reflection") or "").replace("\n", " ")[:400]
        return (
            f"[NARRATIVE] Chapter {d['id']}: {d['label']}\n"
            f"  Span: {(d['start_at'] or '')[:10]} – {(d['end_at'] or '')[:10]}  "
            f"  Watches: {d['watch_count']}\n"
            f"  Night: {_pct(d['night_ratio'])}  Long-form: {_pct(d['long_form_ratio'])}  "
            f"Shorts: {_pct(d['shorts_ratio'])}  Focus: {_pct(d['channel_density_score'])}\n"
            f"  Peak hour: {d['modal_hour']}:00 IST  Median duration: {d['median_duration_seconds']}s\n"
            f"  Reflection: {reflection}"
        )
    except Exception as e:
        return f"[NARRATIVE] ERROR: {e}"


def _pct(v) -> str:
    return f"{v * 100:.0f}%" if v is not None else "—"
