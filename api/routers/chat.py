"""Conversational RAG endpoint — semantic + temporal retrieval → LLM synthesis."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import sqlite_utils

from api.db import get_db
from api.vec import embed_query, search_table
from api.llm import chat as llm_chat, available_models

IST_OFFSET = "+330 minutes"

router = APIRouter(prefix="/api/chat", tags=["chat"])


class TimeRange(BaseModel):
    start: str   # YYYY-MM-DD
    end: str     # YYYY-MM-DD


class ChatRequest(BaseModel):
    question: str
    model: str = "auto"           # "auto" | "claude" | "gpt4o"
    time_range: Optional[TimeRange] = None
    top_semantic: int = 5         # results per lancedb table
    top_watches: int = 20         # watch rows from SQLite when time_range given


class ChatSource(BaseModel):
    kind: str       # "reflection" | "video" | "search" | "watch"
    label: str
    similarity: Optional[float] = None


# ── Context builders ─────────────────────────────────────────────────────────

def _fmt_reflections(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        sim = f"{r['similarity']:.0%}"
        span = f"{r.get('start_at','')[:7]}–{r.get('end_at','')[:7]}"
        text = (r.get('text') or '').replace('\n', ' ')[:300]
        lines.append(f"[Chapter arc {r.get('chapter_id')} | {span} | sim {sim}]\n{text}")
    return "\n\n".join(lines)


def _fmt_videos(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        sim = f"{r['similarity']:.0%}"
        title   = r.get('title') or r.get('text') or ''
        channel = r.get('channel') or ''
        count   = r.get('watch_count', 0)
        ch_str  = f" · {channel}" if channel else ""
        lines.append(f"[Video | sim {sim}] {title}{ch_str} (watched {count}×)")
    return "\n".join(lines)


def _fmt_searches(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        sim   = f"{r['similarity']:.0%}"
        query = r.get('query') or r.get('text') or ''
        span  = f"{r.get('first_seen','')[:7]}–{r.get('last_seen','')[:7]}"
        lines.append(f"[Search | sim {sim}] \"{query}\" (searched {r.get('count',0)}× | {span})")
    return "\n".join(lines)


def _fetch_watches(db: sqlite_utils.Database, tr: TimeRange, limit: int) -> list[dict]:
    rows = db.execute(f"""
        SELECT
            datetime(w.watched_at, '{IST_OFFSET}') AS watched_at_ist,
            COALESCE(vm.title, w.title, w.video_id) AS title,
            COALESCE(vm.channel_title, '')           AS channel,
            ws.is_rewatch,
            ws.session_depth,
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

    keys = ["watched_at_ist", "title", "channel", "is_rewatch", "session_depth", "chapter_label"]
    return [dict(zip(keys, r)) for r in rows]


def _fmt_watches(rows: list[dict], tr: TimeRange) -> str:
    if not rows:
        return f"No watches found between {tr.start} and {tr.end}."
    lines = [f"Watches from {tr.start} to {tr.end} ({len(rows)} shown):"]
    for r in rows:
        ts      = r['watched_at_ist'][:16]
        title   = (r['title'] or '')[:60]
        channel = r['channel'] or ''
        badges  = []
        if r['is_rewatch']:      badges.append('rewatch')
        if (r['session_depth'] or 0) > 3: badges.append('deep session')
        badge_str = f" [{', '.join(badges)}]" if badges else ""
        ch_str    = f" · {channel}" if channel else ""
        lines.append(f"  {ts} | {title}{ch_str}{badge_str}")
    return "\n".join(lines)


def _build_system_prompt() -> str:
    return """You are Echo — an AI assistant that helps a person understand their own digital archaeology.

You have access to six years of their YouTube watch history, search queries, and behavioral chapter data. Answer questions with specific evidence from the context provided. Be honest about uncertainty. Don't psychoanalyze — let the data speak. When the data is ambiguous, say so.

The person asking is Aditya, 23, Indian. All times are in IST (India Standard Time)."""


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

Answer using the context above. Quote specific titles, dates, or patterns when relevant."""


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.post("")
def chat_endpoint(req: ChatRequest, db: sqlite_utils.Database = Depends(get_db)):
    if not req.question.strip():
        raise HTTPException(status_code=422, detail="question cannot be empty")

    # 1. Embed the question
    vector = embed_query(req.question)

    # 2. Semantic retrieval from lancedb
    reflections = search_table("reflections", vector, top=req.top_semantic)
    videos      = search_table("videos",      vector, top=req.top_semantic)
    searches    = search_table("searches",    vector, top=req.top_semantic)

    # 3. Temporal retrieval from SQLite (if time_range given)
    watches = []
    if req.time_range:
        watches = _fetch_watches(db, req.time_range, req.top_watches)

    # 4. Build context
    context_parts: list[tuple[str, str]] = []
    if reflections:
        context_parts.append(("Chapter arcs (semantic)", _fmt_reflections(reflections)))
    if videos:
        context_parts.append(("Related videos (semantic)", _fmt_videos(videos)))
    if searches:
        context_parts.append(("Related search queries (semantic)", _fmt_searches(searches)))
    if watches:
        context_parts.append(("Watch history (time range)", _fmt_watches(watches, req.time_range)))

    if not context_parts:
        raise HTTPException(status_code=503, detail="No context retrieved — lancedb may not be populated")

    # 5. Call LLM
    messages = [
        {"role": "system", "content": _build_system_prompt()},
        {"role": "user",   "content": _build_user_prompt(req.question, context_parts)},
    ]
    answer, model_used = llm_chat(messages, model=req.model, max_tokens=1024, temperature=0.5)

    # 6. Build source list for the UI
    sources: list[dict] = []
    for r in reflections:
        sources.append({"kind": "reflection", "label": f"Ch {r.get('chapter_id')} arc", "similarity": r["similarity"]})
    for r in videos[:3]:
        sources.append({"kind": "video", "label": r.get("title") or r.get("text", "")[:50], "similarity": r["similarity"]})
    for r in searches[:3]:
        sources.append({"kind": "search", "label": f'"{r.get("query") or r.get("text","")}"', "similarity": r["similarity"]})
    if watches:
        sources.append({"kind": "watch", "label": f"{len(watches)} watches ({req.time_range.start}–{req.time_range.end})", "similarity": None})

    return {
        "question": req.question,
        "answer": answer,
        "model": model_used,
        "sources": sources,
        "time_range": req.time_range.model_dump() if req.time_range else None,
    }


@router.get("/models")
def get_available_models():
    """Which models are usable given the current .env keys."""
    return {"models": available_models()}
