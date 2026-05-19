#!/usr/bin/env python3
"""
Echo Layer 3 — GPT-4o narrative reflection.

For each chapter (or the full arc as autobiography), assembles rich context
(fingerprint, top videos, searches, calendar events, watch_signals, and
LIFE CONTEXT pulled from private/annotations.yaml when present) and asks
GPT-4o to write a 200-300 word reflection on what that period of life
looks like through the lens of YouTube.

Inputs:  chapters, chapter_fingerprints, watches, video_metadata,
         yt_searches, calendar_events, watch_signals (echo.db)
         + private/annotations.yaml (optional — LIFE CONTEXT injection)
Outputs: reflections table (appended; kind='chapter' or 'autobiography')

Idempotency: APPENDS — re-running adds new rows rather than replacing
existing ones. Use viewer.py to inspect what's been generated and DELETE
manually if you want a clean re-run.

Cost: ~$0.05-0.30 per full chapter pass (~16 chapters, GPT-4o pricing on
the assembled chapter prompts). The --autobiography pass is one larger
call (~$0.05). ALWAYS preview with --dry-run before a live run — it
prints the assembled prompts without spending tokens, so you can see
what GPT-4o would actually receive.

Usage:
    python reflect.py --dry-run           # print prompts, no API call
    python reflect.py --chapter 5         # reflect on one chapter
    python reflect.py                     # reflect on all chapters
    python reflect.py --autobiography     # full arc synthesis across all chapters
    python reflect.py --dry-run --autobiography

Requires (one of):
    OPENAI_API_KEY    in .env — direct OpenAI
    OPENROUTER_API_KEY in .env — OpenRouter (uses openai/gpt-4o, same quality)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import sqlite_utils

from echo.config import EchoConfig, load_config

# Module-level holder for the active annotations path. Set by run(config) before
# any call to load_annotations(). Tests can monkeypatch this directly.
ANNOTATIONS_PATH: Path | None = None

OPENAI_MODEL      = "gpt-4o"
OPENROUTER_MODEL  = "openai/gpt-4o"  # OpenRouter uses provider-namespaced IDs

CHAPTER_PROMPT_SYSTEM = """\
You are a thoughtful observer helping someone understand a chapter of their life \
through their YouTube watch history. You have access to the videos watched, \
searches made, calendar events, and engagement patterns for a specific time window.

Speak directly to the person in second person ("you were", "you searched for", \
"this was a time when"). Be concrete about what the data actually shows. \
Avoid generic observations — find the specific story in the numbers. \
200–300 words.
"""

AUTOBIOGRAPHY_SYSTEM = """\
You are a thoughtful observer helping someone understand their intellectual and \
emotional journey through years of YouTube watch history, with chapters detected \
by an algorithm that found genuine behavioral shifts.

Write a 500–700 word autobiography-style narrative synthesizing the arc across \
all chapters. Speak in second person. Show the progression: what changed, what \
stayed constant, what the patterns reveal about the person's inner life. \
Be concrete — name actual videos, searches, and patterns. Don't moralize.
"""


# ── API setup ─────────────────────────────────────────────────────────────────


def get_openai_client():
    """Return (client, model_name). Prefers OPENAI_API_KEY; falls back to OPENROUTER_API_KEY."""
    try:
        import openai
    except ImportError:
        print("ERROR: openai package not installed. Run: pip install openai")
        sys.exit(1)

    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        return openai.OpenAI(api_key=key), OPENAI_MODEL

    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    if or_key:
        return openai.OpenAI(
            api_key=or_key,
            base_url="https://openrouter.ai/api/v1",
        ), OPENROUTER_MODEL

    print(
        "ERROR: No API key found.\n"
        "Add one of these to .env:\n"
        "  OPENAI_API_KEY=sk-...        (direct OpenAI)\n"
        "  OPENROUTER_API_KEY=sk-or-... (OpenRouter, uses openai/gpt-4o)"
    )
    sys.exit(1)


def call_gpt4o(client, model: str, system: str, user: str) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature=0.7,
        max_tokens=1000,
    )
    return response.choices[0].message.content.strip()


# ── Life context annotations ─────────────────────────────────────────────────

def load_annotations(chapter_start: str, chapter_end: str) -> list[str]:
    """Return annotation notes whose date range overlaps with [chapter_start, chapter_end]."""
    if ANNOTATIONS_PATH is None or not ANNOTATIONS_PATH.exists():
        return []
    try:
        import yaml
    except ImportError:
        return []  # pyyaml not installed — skip silently
    data = yaml.safe_load(ANNOTATIONS_PATH.read_text(encoding="utf-8")) or {}
    notes = []
    for entry in data.get("annotations", []):
        a_start = str(entry.get("start", ""))
        a_end   = str(entry.get("end",   ""))
        # Overlap: annotation starts before chapter ends AND ends after chapter starts
        if a_start <= chapter_end and a_end >= chapter_start:
            notes.append(str(entry.get("note", "")).strip())
    return notes


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


def build_chapter_prompt(chapter_num: int, ctx: dict, annotations: list[str] | None = None) -> str:
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

    if annotations:
        lines.insert(-1, "")
        lines.insert(-1, "LIFE CONTEXT (ground truth supplied by the subject — treat as fact):")
        for note in annotations:
            for ln in note.splitlines():
                lines.insert(-1, f"  {ln}")

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


def save_reflection(db: sqlite_utils.Database, chapter_id, kind: str, prompt: str, reflection: str, model: str):
    db["reflections"].insert({
        "chapter_id":  chapter_id,
        "kind":        kind,
        "prompt_text": prompt,
        "reflection":  reflection,
        "model":       model,
        "created_at":  datetime.now(timezone.utc).isoformat(),
    })
    db.conn.commit()


# ── Entry point ───────────────────────────────────────────────────────────────


def _push_api_keys_to_env(config: EchoConfig) -> None:
    """Make config.api_keys visible to get_openai_client(), which reads os.environ.

    This is the bridge while reflect.py still uses os.environ-based client init.
    Future cleanup: refactor get_openai_client to take config directly.
    """
    if config.api_keys.openai:
        os.environ.setdefault("OPENAI_API_KEY", config.api_keys.openai)
    if config.api_keys.openrouter:
        os.environ.setdefault("OPENROUTER_API_KEY", config.api_keys.openrouter)


def run(
    config: EchoConfig,
    dry_run: bool = False,
    chapter: int | None = None,
    autobiography: bool = False,
) -> None:
    """Generate per-chapter or whole-arc reflections via GPT-4o.

    Args:
        config:        EchoConfig (uses config.db_path, config.api_keys.openai/openrouter,
                       config.annotations_path).
        dry_run:       Print assembled prompts only; no API calls, no DB writes.
        chapter:       If set, reflect on just chapter N (1-indexed).
        autobiography: If True, run the whole-arc synthesis instead of per-chapter.
    """
    global ANNOTATIONS_PATH
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Wire up the annotations path so load_annotations() finds the right file.
    ANNOTATIONS_PATH = config.annotations_path
    _push_api_keys_to_env(config)

    db = sqlite_utils.Database(config.db_path)
    ensure_reflections_table(db)

    client = None
    model  = OPENAI_MODEL  # overwritten below when not dry-run
    if not dry_run:
        client, model = get_openai_client()

    SEP = "=" * 70

    if autobiography:
        print(f"{SEP}\nECHO LAYER 3 - AUTOBIOGRAPHY\n{SEP}\n")
        prompt = build_autobiography_prompt(db)

        if dry_run:
            print("-- PROMPT ------------------------------------------------------")
            print(prompt)
            print()
            return

        print(f"Calling {model}...", flush=True)
        reflection = call_gpt4o(client, model, AUTOBIOGRAPHY_SYSTEM, prompt)
        save_reflection(db, chapter_id=None, kind="autobiography", prompt=prompt, reflection=reflection, model=model)
        print("\n-- REFLECTION --------------------------------------------------")
        print(reflection)
        print(f"\nSaved to reflections table.")
        return

    # Per-chapter mode
    chapters = db.execute(
        "SELECT id, start_at, end_at, label FROM chapters ORDER BY start_at"
    ).fetchall()

    if not chapters:
        print("ERROR: no chapters found - run `echo detect` first")
        sys.exit(1)

    if chapter:
        idx = chapter - 1
        if idx < 0 or idx >= len(chapters):
            print(f"ERROR: chapter {chapter} not found (have 1-{len(chapters)})")
            sys.exit(1)
        target = [chapters[idx]]
        nums   = [chapter]
    else:
        target = chapters
        nums   = list(range(1, len(chapters) + 1))

    print(f"{SEP}\nECHO LAYER 3 - CHAPTER REFLECTIONS\n{SEP}\n")

    for num, (ch_id, start_at, end_at, label) in zip(nums, target):
        print(f"Chapter {num:>2}  {start_at} -> {end_at}", flush=True)
        ctx         = assemble_chapter_context(db, ch_id, start_at, end_at)
        ann         = load_annotations(start_at, end_at)
        prompt      = build_chapter_prompt(num, ctx, annotations=ann)

        if dry_run:
            print("-- PROMPT ------------------------------------------------------")
            print(prompt)
            print()
            continue

        print(f"  Calling {model}...", end=" ", flush=True)
        reflection = call_gpt4o(client, model, CHAPTER_PROMPT_SYSTEM, prompt)
        save_reflection(db, chapter_id=ch_id, kind="chapter", prompt=prompt, reflection=reflection, model=model)
        print("done")
        print()
        print("-- REFLECTION --------------------------------------------------")
        print(reflection)
        print()

    if not dry_run:
        print(f"\nAll reflections saved to reflections table.")


def main() -> None:
    """Legacy entry for `python -m echo.pipeline.reflect [--dry-run] [--chapter N] [--autobiography]`."""
    parser = argparse.ArgumentParser(description="Echo Layer 3 - GPT-4o narrative reflection")
    parser.add_argument("--dry-run",       action="store_true", help="Print prompts, don't call API")
    parser.add_argument("--chapter",       type=int,            help="Reflect on one chapter by number")
    parser.add_argument("--autobiography", action="store_true", help="Full arc synthesis across all chapters")
    args = parser.parse_args()
    run(load_config(), dry_run=args.dry_run, chapter=args.chapter, autobiography=args.autobiography)


if __name__ == "__main__":
    main()
