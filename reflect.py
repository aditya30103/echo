#!/usr/bin/env python3
"""
Echo Layer 3 — GPT-4o narrative reflection.

For each chapter, assembles rich context (fingerprint, top videos, searches,
calendar, watch signals) and asks GPT-4o to reflect on what that period of
life looks like through the lens of YouTube.

Writes reflections to the `reflections` table in echo.db.

Usage:
    python reflect.py --dry-run           # print prompts, no API call
    python reflect.py --chapter 5         # reflect on one chapter
    python reflect.py                     # reflect on all chapters
    python reflect.py --autobiography     # full arc synthesis across all chapters
    python reflect.py --dry-run --autobiography

Requires:
    OPENAI_API_KEY in .env (or environment)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import sqlite_utils

BASE    = Path(__file__).parent
DB_PATH = BASE / "echo.db"
ENV_PATH = BASE / ".env"

OPENAI_MODEL = "gpt-4o"

CHAPTER_PROMPT_SYSTEM = """\
You are a thoughtful observer helping someone understand a chapter of their life \
through their YouTube watch history. The data spans ages 13–23 for an Indian \
student (IST timezone). You have access to the videos watched, searches made, \
calendar events, and engagement patterns for a specific time window.

Speak directly to the person in second person ("you were", "you searched for", \
"this was a time when"). Be concrete about what the data actually shows. \
Avoid generic observations — find the specific story in the numbers. \
200–300 words.
"""

AUTOBIOGRAPHY_SYSTEM = """\
You are a thoughtful observer helping someone understand their intellectual and \
emotional journey through 6+ years of YouTube watch history. The data spans \
ages 13–23 for an Indian student (IST timezone), with chapters detected by \
an algorithm that found genuine behavioral shifts.

Write a 500–700 word autobiography-style narrative synthesizing the arc across \
all chapters. Speak in second person. Show the progression: what changed, what \
stayed constant, what the patterns reveal about the person's inner life. \
Be concrete — name actual videos, searches, and patterns. Don't moralize.
"""


# ── Env / API setup ───────────────────────────────────────────────────────────

def load_env():
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def get_openai_client():
    try:
        import openai
    except ImportError:
        print("ERROR: openai package not installed. Run: pip install openai")
        sys.exit(1)

    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        print(
            "ERROR: OPENAI_API_KEY not set.\n"
            "Add it to .env:\n"
            "  OPENAI_API_KEY=sk-...\n"
            "Or set the environment variable before running."
        )
        sys.exit(1)

    return openai.OpenAI(api_key=key)


def call_gpt4o(client, system: str, user: str) -> str:
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature=0.7,
        max_tokens=1000,
    )
    return response.choices[0].message.content.strip()


# ── Context assembly ──────────────────────────────────────────────────────────

def assemble_chapter_context(db: sqlite_utils.Database, chapter_id: int, start_iso: str, end_iso: str) -> dict:
    # Chapter fingerprint
    fp_row = db.execute("""
        SELECT cf.*, c.start_at, c.end_at, c.label,
               (SELECT COUNT(*) FROM watches w
                WHERE date(datetime(w.watched_at, '+330 minutes')) BETWEEN c.start_at AND c.end_at) AS n_watches
        FROM chapter_fingerprints cf
        JOIN chapters c ON cf.chapter_id = c.id
        WHERE cf.chapter_id = ?
    """, [chapter_id]).fetchone()

    fp = dict(zip([
        "chapter_id", "top_categories", "median_duration_seconds", "modal_hour",
        "channel_density_score", "night_ratio", "shorts_ratio", "long_form_ratio",
        "start_at", "end_at", "label", "n_watches",
    ], fp_row)) if fp_row else {}

    # Top videos
    top_videos = db.execute("""
        SELECT COALESCE(w.title, w.video_id), COUNT(*) AS n
        FROM watches w
        WHERE date(datetime(w.watched_at, '+330 minutes')) BETWEEN ? AND ?
        GROUP BY w.video_id
        ORDER BY n DESC LIMIT 15
    """, [start_iso, end_iso]).fetchall()

    # YouTube searches
    searches = db.execute("""
        SELECT query, COUNT(*) AS n
        FROM yt_searches
        WHERE date(searched_at) BETWEEN ? AND ?
        GROUP BY query
        ORDER BY n DESC LIMIT 25
    """, [start_iso, end_iso]).fetchall()

    # Calendar events — start_date is stored as raw ICS format (YYYYMMDDTHHMMSSZ),
    # so normalise to ISO before comparing against YYYY-MM-DD chapter boundaries.
    calendar = db.execute("""
        SELECT COALESCE(summary, '(no title)') AS summary, calendar_name, COUNT(*) AS n
        FROM calendar_events
        WHERE substr(start_date,1,4)||'-'||substr(start_date,5,2)||'-'||substr(start_date,7,2)
              BETWEEN ? AND ?
        GROUP BY summary, calendar_name
        ORDER BY n DESC LIMIT 20
    """, [start_iso, end_iso]).fetchall()

    # Watch signals stats for this chapter
    sig_row = db.execute("""
        SELECT
            COUNT(*)                                   AS total,
            ROUND(AVG(ws.session_length), 1)           AS avg_session_len,
            ROUND(SUM(ws.is_rewatch) * 1.0 / COUNT(*), 3)        AS rewatch_rate,
            ROUND(SUM(ws.is_search_driven) * 1.0 / COUNT(*), 3)  AS search_driven_rate,
            ROUND(SUM(ws.is_autoplay) * 1.0 / COUNT(*), 3)       AS autoplay_rate,
            ROUND(SUM(ws.was_bookmarked) * 1.0 / COUNT(*), 3)    AS bookmarked_rate,
            MAX(ws.session_length)                     AS max_session_len
        FROM watch_signals ws
        JOIN watches w ON ws.watch_id = w.id
        WHERE date(datetime(w.watched_at, '+330 minutes')) BETWEEN ? AND ?
    """, [start_iso, end_iso]).fetchone()

    signals = dict(zip([
        "total", "avg_session_len", "rewatch_rate", "search_driven_rate",
        "autoplay_rate", "bookmarked_rate", "max_session_len",
    ], sig_row)) if sig_row else {}

    return {
        "fingerprint": fp,
        "top_videos":  top_videos,
        "searches":    searches,
        "calendar":    calendar,
        "signals":     signals,
    }


def build_chapter_prompt(chapter_num: int, ctx: dict) -> str:
    fp  = ctx["fingerprint"]
    sig = ctx["signals"]

    top_cats = json.loads(fp.get("top_categories") or "{}") if fp else {}
    top_cats_str = "  ".join(f"{c} {p}%" for c, p in top_cats.items())

    videos_str = "\n".join(
        f"  {'x'+str(n):>4}  {title[:80]}"
        for title, n in ctx["top_videos"]
    ) or "  (no data)"

    searches_str = "\n".join(
        f"  {'x'+str(n):>3}  {q[:80]}"
        for q, n in ctx["searches"]
    ) or "  (no searches recorded)"

    calendar_str = "\n".join(
        f"  {'x'+str(n):>3}  [{cal}] {summary[:70]}"
        for summary, cal, n in ctx["calendar"]
    ) or "  (no calendar data for this period)"

    lines = [
        f"CHAPTER {chapter_num}  {fp.get('start_at', '?')} → {fp.get('end_at', '?')}",
        "",
        "SIGNAL FINGERPRINT:",
        f"  Night watching (22:00–04:00 IST):  {fp.get('night_ratio', 0):.0%}",
        f"  Short-form content (≤60s):          {fp.get('shorts_ratio', 0):.0%}",
        f"  Long-form content (>20 min):        {fp.get('long_form_ratio', 0):.0%}",
        f"  Most watched at:                    {fp.get('modal_hour', '?')}:00 IST",
        f"  Median video duration:              {fp.get('median_duration_seconds', 0)/60:.1f} min",
        f"  Channel diversity score:            {fp.get('channel_density_score', 0):.3f}",
        f"  Top categories:                     {top_cats_str or '(unknown)'}",
        "",
        "ENGAGEMENT PATTERNS:",
        f"  Total watches:          {sig.get('total', 0):,}",
        f"  Average session length: {sig.get('avg_session_len', 0):.1f} videos",
        f"  Longest session:        {sig.get('max_session_len', 0)} videos",
        f"  Rewatch rate:           {sig.get('rewatch_rate', 0):.0%}",
        f"  Search-driven rate:     {sig.get('search_driven_rate', 0):.0%}",
        f"  Autoplay proxy rate:    {sig.get('autoplay_rate', 0):.0%}",
        f"  Bookmarked-then-watched:{sig.get('bookmarked_rate', 0):.0%}",
        "",
        "TOP 15 VIDEOS (by rewatch count):",
        videos_str,
        "",
        "YOUTUBE SEARCHES:",
        searches_str,
        "",
        "CALENDAR CONTEXT:",
        calendar_str,
        "",
        "What does this chapter reveal about this person's life, interests, and inner state?",
    ]
    return "\n".join(lines)


def build_autobiography_prompt(db: sqlite_utils.Database) -> str:
    chapters = db.execute(
        "SELECT id, start_at, end_at, label FROM chapters ORDER BY start_at"
    ).fetchall()

    sections = []
    for ch_id, start_at, end_at, label in chapters:
        ctx = assemble_chapter_context(db, ch_id, start_at, end_at)
        fp  = ctx["fingerprint"]
        top_cats = json.loads(fp.get("top_categories") or "{}") if fp else {}
        top_cat  = list(top_cats.keys())[0] if top_cats else "?"
        sig = ctx["signals"]
        top_vid  = ctx["top_videos"][0][0][:60] if ctx["top_videos"] else "?"
        num = chapters.index((ch_id, start_at, end_at, label)) + 1
        sections.append(
            f"Ch{num:>2} ({start_at} → {end_at})  "
            f"n={sig.get('total',0):>4}  "
            f"night={fp.get('night_ratio',0):.0%}  "
            f"shorts={fp.get('shorts_ratio',0):.0%}  "
            f"long={fp.get('long_form_ratio',0):.0%}  "
            f"top_cat={top_cat}  "
            f"rewatch={sig.get('rewatch_rate',0):.0%}  "
            f'top_vid="{top_vid}"'
        )

    lines = [
        "FULL WATCH HISTORY ARC  (2020–2026)",
        "Each row = one behavioral chapter detected by changepoint analysis:",
        "",
        *sections,
        "",
        "Write a 500–700 word autobiography-style narrative synthesizing the arc.",
    ]
    return "\n".join(lines)


# ── DB write ──────────────────────────────────────────────────────────────────

def ensure_reflections_table(db: sqlite_utils.Database):
    db.execute("""
        CREATE TABLE IF NOT EXISTS reflections (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_id   INTEGER REFERENCES chapters(id),
            kind         TEXT NOT NULL,   -- 'chapter' or 'autobiography'
            prompt_text  TEXT,
            reflection   TEXT,
            model        TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        )
    """)
    db.conn.commit()


def save_reflection(db: sqlite_utils.Database, chapter_id, kind: str, prompt: str, reflection: str):
    db["reflections"].insert({
        "chapter_id":  chapter_id,
        "kind":        kind,
        "prompt_text": prompt,
        "reflection":  reflection,
        "model":       OPENAI_MODEL,
        "created_at":  datetime.now(timezone.utc).isoformat(),
    })
    db.conn.commit()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_env()

    parser = argparse.ArgumentParser(description="Echo Layer 3 — GPT-4o narrative reflection")
    parser.add_argument("--dry-run",       action="store_true", help="Print prompts, don't call API")
    parser.add_argument("--chapter",       type=int,            help="Reflect on one chapter by number")
    parser.add_argument("--autobiography", action="store_true", help="Full arc synthesis across all chapters")
    args = parser.parse_args()

    db = sqlite_utils.Database(DB_PATH)
    ensure_reflections_table(db)

    client = None
    if not args.dry_run:
        client = get_openai_client()

    SEP = "=" * 70

    if args.autobiography:
        print(f"{SEP}\nECHO LAYER 3 — AUTOBIOGRAPHY\n{SEP}\n")
        prompt = build_autobiography_prompt(db)

        if args.dry_run:
            print("── PROMPT ──────────────────────────────────────────────────────")
            print(prompt)
            print()
            return

        print(f"Calling {OPENAI_MODEL}...", flush=True)
        reflection = call_gpt4o(client, AUTOBIOGRAPHY_SYSTEM, prompt)
        save_reflection(db, chapter_id=None, kind="autobiography", prompt=prompt, reflection=reflection)
        print("\n── REFLECTION ──────────────────────────────────────────────────")
        print(reflection)
        print(f"\nSaved to reflections table.")
        return

    # Per-chapter mode
    chapters = db.execute(
        "SELECT id, start_at, end_at, label FROM chapters ORDER BY start_at"
    ).fetchall()

    if not chapters:
        print("ERROR: no chapters found — run detect.py first")
        sys.exit(1)

    if args.chapter:
        idx = args.chapter - 1
        if idx < 0 or idx >= len(chapters):
            print(f"ERROR: chapter {args.chapter} not found (have 1–{len(chapters)})")
            sys.exit(1)
        target = [chapters[idx]]
        nums   = [args.chapter]
    else:
        target = chapters
        nums   = list(range(1, len(chapters) + 1))

    print(f"{SEP}\nECHO LAYER 3 — CHAPTER REFLECTIONS\n{SEP}\n")

    for num, (ch_id, start_at, end_at, label) in zip(nums, target):
        print(f"Chapter {num:>2}  {start_at} → {end_at}", flush=True)
        ctx    = assemble_chapter_context(db, ch_id, start_at, end_at)
        prompt = build_chapter_prompt(num, ctx)

        if args.dry_run:
            print("── PROMPT ──────────────────────────────────────────────────────")
            print(prompt)
            print()
            continue

        print(f"  Calling {OPENAI_MODEL}...", end=" ", flush=True)
        reflection = call_gpt4o(client, CHAPTER_PROMPT_SYSTEM, prompt)
        save_reflection(db, chapter_id=ch_id, kind="chapter", prompt=prompt, reflection=reflection)
        print("done")
        print()
        print("── REFLECTION ──────────────────────────────────────────────────")
        print(reflection)
        print()

    if not args.dry_run:
        print(f"\nAll reflections saved to reflections table.")


if __name__ == "__main__":
    main()
