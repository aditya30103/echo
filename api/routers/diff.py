"""Psyche diff — behavioral delta narrative between two chapters."""

import json
import os
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import sqlite_utils

from api.db import get_db

BASE = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE))

router = APIRouter(prefix="/api/diff", tags=["diff"])

# GPT-4o via OpenRouter; falls back to gpt-4o-mini if 4o is unavailable
CHAT_MODEL = "openai/gpt-4o"


class DiffRequest(BaseModel):
    chapter_a: int
    chapter_b: int
    force: bool = False  # bypass cache


def _get_chat_client():
    from embed_common import load_env
    load_env()
    import openai
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        return openai.OpenAI(api_key=key), "gpt-4o"
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    if or_key:
        return openai.OpenAI(
            api_key=or_key,
            base_url="https://openrouter.ai/api/v1",
        ), CHAT_MODEL
    raise RuntimeError("No API key found — set OPENAI_API_KEY or OPENROUTER_API_KEY in .env")


def _fetch_chapter(db: sqlite_utils.Database, chapter_id: int) -> dict:
    row = db.execute("""
        SELECT c.id, c.label, c.start_at, c.end_at,
               cf.night_ratio, cf.modal_hour, cf.long_form_ratio, cf.shorts_ratio,
               cf.channel_density_score, cf.median_duration_seconds, cf.top_categories,
               r.reflection
        FROM chapters c
        LEFT JOIN chapter_fingerprints cf ON cf.chapter_id = c.id
        LEFT JOIN reflections r ON r.chapter_id = c.id AND r.kind = 'chapter'
        WHERE c.id = ?
    """, [chapter_id]).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Chapter {chapter_id} not found")
    keys = ["id", "label", "start_at", "end_at",
            "night_ratio", "modal_hour", "long_form_ratio", "shorts_ratio",
            "channel_density_score", "median_duration_seconds", "top_categories_raw",
            "reflection"]
    d = dict(zip(keys, row))
    raw = d.pop("top_categories_raw")
    try:
        d["top_categories"] = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        d["top_categories"] = {}
    return d


def _build_prompt(a: dict, b: dict) -> str:
    def fmt_chapter(ch: dict) -> str:
        cats = ", ".join(f"{k} ({v:.0f}%)" for k, v in list(ch["top_categories"].items())[:4])
        dur = f"{ch['median_duration_seconds'] / 60:.0f} min" if ch["median_duration_seconds"] else "unknown"
        return f"""Chapter {ch['id']} — {ch['label']}
Period: {ch['start_at'][:10]} to {ch['end_at'][:10]}
Behavioral fingerprint:
  Night watching (11 PM–4 AM): {(ch['night_ratio'] or 0) * 100:.0f}%
  Peak hour (IST): {ch['modal_hour']}:00
  Long-form content (>20 min): {(ch['long_form_ratio'] or 0) * 100:.0f}%
  Shorts: {(ch['shorts_ratio'] or 0) * 100:.0f}%
  Channel concentration: {(ch['channel_density_score'] or 0):.2f} (0=scattered, 1=obsessed)
  Median watch duration: {dur}
  Top content categories: {cats}
Reflection (GPT-4o chapter narrative):
{ch['reflection'] or '(no reflection yet)'}"""

    return f"""You are analyzing six years of a person's YouTube watch history, organized into behavioral chapters by a changepoint detection algorithm. Two chapters are compared below.

Your task: write a psyche diff — a short, honest narrative (200–300 words) that describes how this person's *inner world* changed between these two periods. Focus on the behavioral signals, not just events. What shifted in how they used screens? What does the timing, depth, and content mix reveal about their state of mind? Say something they might not have realized about themselves.

Do not summarize the reflections. Use them as context, but synthesize something new. Be specific, be honest, avoid corporate wellness language.

---

{fmt_chapter(a)}

---

{fmt_chapter(b)}

---

Write the psyche diff now. Start with the sharpest contrast you see between the two periods."""


def _ensure_cache_table(db: sqlite_utils.Database):
    if "diffs" not in db.table_names():
        db["diffs"].create({
            "id": str,        # "{min_id}-{max_id}"
            "chapter_a": int,
            "chapter_b": int,
            "narrative": str,
            "model": str,
            "created_at": str,
        }, pk="id")


@router.post("")
def psyche_diff(req: DiffRequest, db: sqlite_utils.Database = Depends(get_db)):
    if req.chapter_a == req.chapter_b:
        raise HTTPException(status_code=422, detail="Choose two different chapters")

    _ensure_cache_table(db)

    lo, hi = sorted([req.chapter_a, req.chapter_b])
    cache_key = f"{lo}-{hi}"

    if not req.force:
        cached = db.execute(
            "SELECT narrative, model, created_at FROM diffs WHERE id = ?", [cache_key]
        ).fetchone()
        if cached:
            return {
                "chapter_a": req.chapter_a,
                "chapter_b": req.chapter_b,
                "narrative": cached[0],
                "model": cached[1],
                "cached": True,
                "created_at": cached[2],
            }

    a = _fetch_chapter(db, req.chapter_a)
    b = _fetch_chapter(db, req.chapter_b)

    client, model = _get_chat_client()
    prompt = _build_prompt(a, b)

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
        temperature=0.7,
    )
    narrative = resp.choices[0].message.content.strip()

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    db["diffs"].upsert({
        "id": cache_key,
        "chapter_a": req.chapter_a,
        "chapter_b": req.chapter_b,
        "narrative": narrative,
        "model": model,
        "created_at": now,
    }, pk="id")

    return {
        "chapter_a": req.chapter_a,
        "chapter_b": req.chapter_b,
        "chapter_a_data": a,
        "chapter_b_data": b,
        "narrative": narrative,
        "model": model,
        "cached": False,
        "created_at": now,
    }


@router.get("/chapters")
def get_chapters_for_diff(db: sqlite_utils.Database = Depends(get_db)):
    """Lightweight chapter list for the diff selector dropdowns."""
    rows = db.execute("""
        SELECT c.id, c.label, c.start_at, c.end_at,
               cf.night_ratio, cf.modal_hour, cf.long_form_ratio, cf.shorts_ratio,
               cf.channel_density_score, cf.median_duration_seconds, cf.top_categories
        FROM chapters c
        LEFT JOIN chapter_fingerprints cf ON cf.chapter_id = c.id
        ORDER BY c.id
    """).fetchall()
    keys = ["id", "label", "start_at", "end_at",
            "night_ratio", "modal_hour", "long_form_ratio", "shorts_ratio",
            "channel_density_score", "median_duration_seconds", "top_categories_raw"]
    result = []
    for row in rows:
        d = dict(zip(keys, row))
        raw = d.pop("top_categories_raw")
        try:
            d["top_categories"] = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            d["top_categories"] = {}
        result.append(d)
    return {"chapters": result}
