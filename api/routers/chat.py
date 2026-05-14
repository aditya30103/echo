"""Conversational RAG endpoint — semantic + temporal retrieval → LLM synthesis."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import sqlite_utils

from api.constants import IST_OFFSET
from api.db import get_db
from api.vec import embed_query, search_table
from api.llm import chat as llm_chat, available_models

router = APIRouter(prefix="/api/chat", tags=["chat"])

# ICS date columns are stored as YYYYMMDD or YYYYMMDDTHHMMSSZ — normalise to ISO.
_ICS_TO_ISO = "substr(start_date,1,4)||'-'||substr(start_date,5,2)||'-'||substr(start_date,7,2)"


class TimeRange(BaseModel):
    start: str   # YYYY-MM-DD
    end: str     # YYYY-MM-DD


class ChatRequest(BaseModel):
    question: str
    model: str = "auto"              # "auto" | "claude" | "gpt4o"
    time_range: Optional[TimeRange] = None
    top_semantic: int = 5            # results per lancedb table
    top_watches: int = 20            # watch rows from SQLite when time_range given
    min_session_depth: int = 5       # binge sessions of at least this many videos
    top_sessions: int = 10           # max binge sessions to include
    include_reflections: bool = True # set False to skip chapter arc context


class ChatSource(BaseModel):
    kind: str       # "reflection" | "video" | "search" | "watch" | "google_search" | "session" | "calendar"
    label: str
    similarity: Optional[float] = None


# ── Context builders ─────────────────────────────────────────────────────────

def _fmt_reflections(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        sim  = f"{r['similarity']:.0%}"
        span = f"{r.get('start_at','')[:7]}–{r.get('end_at','')[:7]}"
        text = (r.get('text') or '').replace('\n', ' ')[:300]
        lines.append(f"[Chapter arc {r.get('chapter_id')} | {span} | sim {sim}]\n{text}")
    return "\n\n".join(lines)


def _enrich_videos(rows: list[dict], db: sqlite_utils.Database) -> list[dict]:
    """Batch-enrich lancedb video rows with first/last seen, chapters, rewatch count."""
    video_ids = [r["video_id"] for r in rows if r.get("video_id")]
    if not video_ids:
        return rows
    placeholders = ",".join("?" * len(video_ids))
    enriched = db.execute(f"""
        SELECT
            w.video_id,
            MIN(datetime(w.watched_at, '{IST_OFFSET}')) AS first_seen,
            MAX(datetime(w.watched_at, '{IST_OFFSET}')) AS last_seen,
            GROUP_CONCAT(DISTINCT c.label)              AS chapters,
            MAX(ws.rewatch_count)                       AS max_rewatch_count
        FROM watches w
        LEFT JOIN watch_signals ws ON ws.watch_id = w.id
        LEFT JOIN chapters c
               ON datetime(w.watched_at, '{IST_OFFSET}') BETWEEN c.start_at AND c.end_at
        WHERE w.video_id IN ({placeholders})
        GROUP BY w.video_id
    """, video_ids).fetchall()
    lookup = {e[0]: e for e in enriched}
    for r in rows:
        e = lookup.get(r.get("video_id"))
        if e:
            r["first_seen_ist"]     = (e[1] or "")[:10]
            r["last_seen_ist"]      = (e[2] or "")[:10]
            r["chapters_seen"]      = e[3] or ""
            r["max_rewatch_count"]  = e[4] or 0
    return rows


def _fmt_videos(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        sim     = f"{r['similarity']:.0%}"
        title   = r.get('title') or r.get('text') or ''
        channel = r.get('channel') or ''
        count   = r.get('watch_count', 0)
        first   = r.get('first_seen_ist', '')
        last    = r.get('last_seen_ist', '')
        chapters = r.get('chapters_seen', '')
        rewatch  = r.get('max_rewatch_count') or 0

        ch_str      = f" · {channel}" if channel else ""
        date_str    = f" · first: {first}" if first else ""
        span_str    = f"–{last}" if last and last != first else ""
        chap_str    = f" · in: {chapters}" if chapters else ""
        rewatch_str = f" · rewatched {rewatch}×" if rewatch > 1 else ""
        lines.append(
            f"[Video | sim {sim}] {title}{ch_str} "
            f"(watched {count}×{rewatch_str}{date_str}{span_str}{chap_str})"
        )
    return "\n".join(lines)


def _fmt_searches(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        sim   = f"{r['similarity']:.0%}"
        query = r.get('query') or r.get('text') or ''
        span  = f"{r.get('first_seen','')[:7]}–{r.get('last_seen','')[:7]}"
        lines.append(f"[YouTube search | sim {sim}] \"{query}\" (searched {r.get('count',0)}× | {span})")
    return "\n".join(lines)


def _fmt_google_searches(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        sim   = f"{r['similarity']:.0%}"
        query = r.get('query') or r.get('text') or ''
        span  = f"{r.get('first_seen','')[:7]}–{r.get('last_seen','')[:7]}"
        lines.append(f"[Google search | sim {sim}] \"{query}\" (searched {r.get('count',0)}× | {span})")
    return "\n".join(lines)


def _fetch_watches(db: sqlite_utils.Database, tr: TimeRange, limit: int) -> list[dict]:
    rows = db.execute(f"""
        SELECT
            datetime(w.watched_at, '{IST_OFFSET}') AS watched_at_ist,
            COALESCE(vm.title, w.title, w.video_id) AS title,
            COALESCE(vm.channel_title, '')           AS channel,
            ws.is_rewatch,
            ws.session_depth,
            ws.is_search_driven,
            ws.was_bookmarked,
            ws.is_autoplay,
            c.label AS chapter_label
        FROM watches w
        LEFT JOIN video_metadata vm ON w.video_id = vm.video_id
        LEFT JOIN watch_signals  ws ON ws.watch_id = w.id
        LEFT JOIN chapters        c ON datetime(w.watched_at, '{IST_OFFSET}')
                                           BETWEEN c.start_at AND c.end_at
        WHERE date(datetime(w.watched_at, '{IST_OFFSET}')) BETWEEN ? AND ?
        ORDER BY w.watched_at
        LIMIT ?
    """, [tr.start, tr.end, limit]).fetchall()

    keys = ["watched_at_ist", "title", "channel", "is_rewatch", "session_depth",
            "is_search_driven", "was_bookmarked", "is_autoplay", "chapter_label"]
    return [dict(zip(keys, r)) for r in rows]


def _fmt_watches(rows: list[dict], tr: TimeRange) -> str:
    if not rows:
        return f"No watches found between {tr.start} and {tr.end}."
    lines = [f"Watches from {tr.start} to {tr.end} ({len(rows)} shown):"]
    for r in rows:
        ts      = r['watched_at_ist'][:16]
        title   = (r['title'] or '')[:60]
        channel = r['channel'] or ''
        chapter = r['chapter_label'] or ''

        badges = []
        if r['is_search_driven']:  badges.append('searched')
        if r['was_bookmarked']:    badges.append('bookmarked')
        if r['is_rewatch']:        badges.append('rewatch')
        if r['is_autoplay']:       badges.append('autoplay')
        if (r['session_depth'] or 0) > 3: badges.append('deep session')

        badge_str   = f" [{', '.join(badges)}]" if badges else ""
        ch_str      = f" · {channel}" if channel else ""
        chapter_str = f" · {chapter}" if chapter else ""
        lines.append(f"  {ts} | {title}{ch_str}{chapter_str}{badge_str}")
    return "\n".join(lines)


def _fetch_calendar(db: sqlite_utils.Database, tr: TimeRange, limit: int = 50) -> list[dict]:
    """Fetch calendar events overlapping the time range (±7 days padding)."""
    rows = db.execute(f"""
        SELECT
            {_ICS_TO_ISO}   AS event_date,
            summary,
            calendar_name
        FROM calendar_events
        WHERE {_ICS_TO_ISO} BETWEEN date(?, '-7 days') AND date(?, '+3 days')
          AND summary IS NOT NULL
        ORDER BY start_date
        LIMIT ?
    """, [tr.start, tr.end, limit]).fetchall()
    keys = ["event_date", "summary", "calendar_name"]
    return [dict(zip(keys, r)) for r in rows]


def _fmt_calendar(rows: list[dict], tr: TimeRange) -> str:
    if not rows:
        return f"No calendar events found near {tr.start}–{tr.end}."
    lines = [f"Calendar events near {tr.start}–{tr.end}:"]
    for r in rows:
        cal = f" ({r['calendar_name']})" if r['calendar_name'] else ""
        lines.append(f"  {r['event_date']} | {r['summary']}{cal}")
    return "\n".join(lines)


def _fetch_sessions(
    db: sqlite_utils.Database, tr: TimeRange, min_depth: int, limit: int
) -> list[dict]:
    """Fetch binge sessions (≥ min_depth videos) that fall within the time range."""
    rows = db.execute(f"""
        SELECT
            ws.session_id,
            MAX(ws.session_length)                              AS session_length,
            MIN(datetime(w.watched_at, '{IST_OFFSET}'))        AS session_start,
            MAX(datetime(w.watched_at, '{IST_OFFSET}'))        AS session_end,
            CAST(
                (julianday(MAX(datetime(w.watched_at, '{IST_OFFSET}')))
                 - julianday(MIN(datetime(w.watched_at, '{IST_OFFSET}'))))
                * 24 * 60 AS INTEGER
            )                                                   AS duration_minutes
        FROM watch_signals ws
        JOIN watches w ON ws.watch_id = w.id
        WHERE date(datetime(w.watched_at, '{IST_OFFSET}')) BETWEEN ? AND ?
          AND ws.session_length >= ?
        GROUP BY ws.session_id
        ORDER BY MAX(ws.session_length) DESC
        LIMIT ?
    """, [tr.start, tr.end, min_depth, limit]).fetchall()
    keys = ["session_id", "session_length", "session_start", "session_end", "duration_minutes"]
    return [dict(zip(keys, r)) for r in rows]


def _fmt_sessions(rows: list[dict], tr: TimeRange, min_depth: int) -> str:
    if not rows:
        return f"No binge sessions (≥{min_depth} videos) found between {tr.start} and {tr.end}."
    lines = [f"Binge sessions from {tr.start} to {tr.end} (≥{min_depth} videos, longest first):"]
    for r in rows:
        start = r['session_start'][:16] if r['session_start'] else '?'
        end   = r['session_end'][:16]   if r['session_end']   else '?'
        dur   = r['duration_minutes'] or 0
        h, m  = divmod(dur, 60)
        dur_str = f"{h}h {m}m" if h else f"{m}m"
        lines.append(
            f"  {start}–{end[:11].strip()} IST | {r['session_length']} videos | {dur_str}"
        )
    return "\n".join(lines)


def _build_system_prompt() -> str:
    return """You are Echo — an AI assistant that helps a person understand their own digital archaeology.

You have access to:
- Six years of YouTube watch history (2020–2026) with per-watch engagement signals:
  [searched] = actively sought via YouTube search
  [bookmarked] = saved to Watch Later (intentional)
  [autoplay] = passively landed here (same channel, <3 min gap)
  [rewatch] = watched this video before
  [deep session] = session depth >3 (rabbit hole)
- YouTube and Google search queries (what was on their mind)
- 16 behavioral chapters detected by changepoint analysis, each with a GPT-4o narrative reflection
- Personal calendar events (2022–2026) — lectures, exams, meetings, deadlines
- Binge session structure: which sessions were long rabbit holes vs. casual browsing

Answer with specific evidence. When you see [searched] or [bookmarked], call it out — that was an active choice, not passive consumption. When calendar events overlap with watch patterns, name the correlation explicitly. Data before 2020 is missing.

The person asking is Aditya, 23, Indian. All times are IST (India Standard Time)."""


def _build_user_prompt(question: str, context_parts: list[tuple[str, str]]) -> str:
    context_str = "\n\n---\n\n".join(
        f"## {label}\n{content}"
        for label, content in context_parts
        if content.strip()
    )
    return f"""Context retrieved from Aditya's data:

{context_str}

---

Question: {question}

Answer using the context above. Quote specific titles, dates, or patterns when relevant. Call out agency signals ([searched], [bookmarked]) vs. passive consumption ([autoplay]) where they appear."""


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.post("")
def chat_endpoint(req: ChatRequest, db: sqlite_utils.Database = Depends(get_db)):
    if not req.question.strip():
        raise HTTPException(status_code=422, detail="question cannot be empty")

    # 1. Embed the question
    vector = embed_query(req.question)

    # 2. Semantic retrieval from lancedb (all 4 tables)
    reflections    = search_table("reflections", vector, top=req.top_semantic) if req.include_reflections else []
    videos         = search_table("videos",         vector, top=req.top_semantic)
    yt_searches    = search_table("searches",       vector, top=req.top_semantic)
    google_results = search_table("google_searches", vector, top=req.top_semantic)

    # 3. Temporal retrieval from SQLite (when time_range given)
    watches  = []
    calendar = []
    sessions = []
    if req.time_range:
        watches  = _fetch_watches(db, req.time_range, req.top_watches)
        calendar = _fetch_calendar(db, req.time_range)
        sessions = _fetch_sessions(db, req.time_range, req.min_session_depth, req.top_sessions)

    # 4. Enrich lancedb video rows with SQLite temporal metadata
    if videos:
        videos = _enrich_videos(videos, db)

    # 5. Build context parts for the prompt
    context_parts: list[tuple[str, str]] = []
    if reflections:
        context_parts.append(("Chapter arcs (semantic)", _fmt_reflections(reflections)))
    if videos:
        context_parts.append(("Related videos (semantic)", _fmt_videos(videos)))
    if yt_searches:
        context_parts.append(("Related YouTube searches (semantic)", _fmt_searches(yt_searches)))
    if google_results:
        context_parts.append(("Related Google searches (semantic)", _fmt_google_searches(google_results)))
    if watches:
        context_parts.append(("Watch history (time range)", _fmt_watches(watches, req.time_range)))
    if sessions:
        context_parts.append(
            ("Binge sessions (time range)",
             _fmt_sessions(sessions, req.time_range, req.min_session_depth))
        )
    if calendar:
        context_parts.append(("Calendar events (time range)", _fmt_calendar(calendar, req.time_range)))

    if not context_parts:
        raise HTTPException(
            status_code=503,
            detail="No context retrieved — lancedb may not be populated (run embed.py)"
        )

    # 6. Call LLM
    messages = [
        {"role": "system", "content": _build_system_prompt()},
        {"role": "user",   "content": _build_user_prompt(req.question, context_parts)},
    ]
    answer, model_used = llm_chat(messages, model=req.model, max_tokens=1024, temperature=0.5)

    # 7. Build source list for the UI
    sources: list[dict] = []
    for r in reflections:
        sources.append({"kind": "reflection", "label": f"Ch {r.get('chapter_id')} arc", "similarity": r["similarity"]})
    for r in videos[:3]:
        sources.append({"kind": "video", "label": r.get("title") or r.get("text", "")[:50], "similarity": r["similarity"]})
    for r in yt_searches[:3]:
        sources.append({"kind": "search", "label": f'"{r.get("query") or r.get("text","")}"', "similarity": r["similarity"]})
    for r in google_results[:2]:
        sources.append({"kind": "google_search", "label": f'"{r.get("query") or r.get("text","")}"', "similarity": r["similarity"]})
    if watches:
        sources.append({"kind": "watch", "label": f"{len(watches)} watches ({req.time_range.start}–{req.time_range.end})", "similarity": None})
    if sessions:
        sources.append({"kind": "session", "label": f"{len(sessions)} binge sessions", "similarity": None})
    if calendar:
        sources.append({"kind": "calendar", "label": f"{len(calendar)} calendar events", "similarity": None})

    return {
        "question":   req.question,
        "answer":     answer,
        "model":      model_used,
        "sources":    sources,
        "time_range": req.time_range.model_dump() if req.time_range else None,
    }


@router.get("/models")
def get_available_models():
    """Which models are usable given the current .env keys."""
    return {"models": available_models()}
