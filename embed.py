#!/usr/bin/env python3
"""
Echo Layer 4 — Semantic embeddings.

Embeds three corpora and stores them in a local lancedb database:
  - reflections  : 16 chapter narratives (for arc-level semantic search)
  - videos       : unique video titles + channel (for content-level search)
  - searches     : unique YouTube search queries (for intent-level search)

Model: text-embedding-3-small (1536 dims, via OpenAI or OpenRouter)
Store: ./lancedb/   (local, gitignored — regenerable from echo.db)

Usage:
    python embed.py              # embed all three tables
    python embed.py --dry-run    # show counts and sample texts, no API calls
    python embed.py --table reflections   # embed one table only
    python embed.py --table videos
    python embed.py --table searches

Idempotent: drops and recreates each table on every run.
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import lancedb
import sqlite_utils

BASE             = Path(__file__).parent
DB_PATH          = BASE / "echo.db"
ENV_PATH         = BASE / ".env"
LANCEDB_PATH     = BASE / "lancedb"

OPENAI_EMBED_MODEL      = "text-embedding-3-small"
OPENROUTER_EMBED_MODEL  = "openai/text-embedding-3-small"
EMBED_DIMS              = 1536

BATCH_SIZE = 512  # inputs per embeddings API request; OpenAI hard limit is 2048


# ── Env / API ─────────────────────────────────────────────────────────────────

def load_env():
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def get_embed_client():
    """Return (client, model_name). Prefers OPENAI_API_KEY; falls back to OPENROUTER_API_KEY."""
    try:
        import openai
    except ImportError:
        print("ERROR: openai package not installed. Run: pip install openai")
        sys.exit(1)

    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        return openai.OpenAI(api_key=key), OPENAI_EMBED_MODEL

    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    if or_key:
        return openai.OpenAI(
            api_key=or_key,
            base_url="https://openrouter.ai/api/v1",
        ), OPENROUTER_EMBED_MODEL

    print(
        "ERROR: No API key found.\n"
        "Add one of these to .env:\n"
        "  OPENAI_API_KEY=sk-...        (direct OpenAI)\n"
        "  OPENROUTER_API_KEY=sk-or-... (OpenRouter)"
    )
    sys.exit(1)


# ── Embedding ─────────────────────────────────────────────────────────────────

def embed_batch(client, model: str, texts: list[str]) -> list[list[float]]:
    """Embed a list of strings in one API call. len(texts) must be <= BATCH_SIZE."""
    response = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


def embed_all(client, model: str, texts: list[str], label: str) -> list[list[float]]:
    """Embed texts in batches, printing progress."""
    vectors = []
    total   = len(texts)
    for i in range(0, total, BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        end   = min(i + BATCH_SIZE, total)
        print(f"  Embedding {label}: {i+1}–{end} / {total}...", flush=True)
        vectors.extend(embed_batch(client, model, batch))
    return vectors


# ── Data loaders ──────────────────────────────────────────────────────────────

def load_reflections(db: sqlite_utils.Database) -> list[dict]:
    rows = db.execute("""
        SELECT r.chapter_id, c.start_at, c.end_at, r.reflection
        FROM reflections r
        JOIN chapters c ON r.chapter_id = c.id
        WHERE r.kind = 'chapter'
        ORDER BY c.start_at
    """).fetchall()
    return [
        {
            "chapter_id": ch_id,
            "start_at":   start,
            "end_at":     end,
            "text":       reflection,
        }
        for ch_id, start, end, reflection in rows
    ]


def load_videos(db: sqlite_utils.Database) -> list[dict]:
    # One row per unique video_id; prefer enriched title from video_metadata.
    # Embed "title | channel" so channel context is in the vector.
    rows = db.execute("""
        SELECT
            w.video_id,
            COALESCE(vm.title, w.title, w.video_id)   AS title,
            COALESCE(vm.channel_title, '')             AS channel,
            COUNT(*)                                   AS watch_count
        FROM watches w
        LEFT JOIN video_metadata vm ON w.video_id = vm.video_id
        GROUP BY w.video_id
        ORDER BY watch_count DESC
    """).fetchall()
    records = []
    for video_id, title, channel, watch_count in rows:
        text = f"{title} | {channel}" if channel else title
        records.append({
            "video_id":    video_id,
            "title":       title,
            "channel":     channel,
            "watch_count": watch_count,
            "text":        text,
        })
    return records


def load_searches(db: sqlite_utils.Database) -> list[dict]:
    rows = db.execute("""
        SELECT query, COUNT(*) AS n,
               MIN(date(searched_at)) AS first_seen,
               MAX(date(searched_at)) AS last_seen
        FROM yt_searches
        GROUP BY query
        ORDER BY n DESC
    """).fetchall()
    return [
        {
            "query":      query,
            "count":      n,
            "first_seen": first_seen,
            "last_seen":  last_seen,
            "text":       query,
        }
        for query, n, first_seen, last_seen in rows
    ]


# ── lancedb writes ────────────────────────────────────────────────────────────

def write_table(ldb, name: str, records: list[dict], vectors: list[list[float]]):
    """Drop-and-recreate a lancedb table with embedded records."""
    if name in ldb.list_tables():
        ldb.drop_table(name)
        print(f"  Dropped existing '{name}' table.")

    rows = []
    for rec, vec in zip(records, vectors):
        row = dict(rec)
        row["vector"] = vec
        rows.append(row)

    table = ldb.create_table(name, data=rows)
    print(f"  Created '{name}' table: {len(rows)} rows, {EMBED_DIMS}-dim vectors.")
    return table


# ── Main ──────────────────────────────────────────────────────────────────────

ALL_TABLES = ["reflections", "videos", "searches"]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_env()

    parser = argparse.ArgumentParser(description="Echo Layer 4 — semantic embeddings")
    parser.add_argument("--dry-run", action="store_true", help="Show counts, no API calls")
    parser.add_argument("--table",   choices=ALL_TABLES,  help="Embed one table only")
    args = parser.parse_args()

    tables_to_run = [args.table] if args.table else ALL_TABLES

    db = sqlite_utils.Database(DB_PATH)

    # Load data
    loaders = {
        "reflections": load_reflections,
        "videos":      load_videos,
        "searches":    load_searches,
    }
    datasets = {name: loaders[name](db) for name in tables_to_run}

    SEP = "=" * 60
    print(f"{SEP}\nECHO LAYER 4 — EMBEDDINGS\n{SEP}\n")

    if args.dry_run:
        for name, records in datasets.items():
            print(f"{name}: {len(records)} items")
            for rec in records[:3]:
                print(f"  sample: {rec['text'][:80]}")
            print()
        return

    client, model = get_embed_client()
    print(f"Provider: {model}\n")

    ldb = lancedb.connect(str(LANCEDB_PATH))

    for name, records in datasets.items():
        print(f"-- {name} --")
        if not records:
            print(f"  No data found — skipping.")
            continue
        texts   = [r["text"] for r in records]
        vectors = embed_all(client, model, texts, name)
        write_table(ldb, name, records, vectors)
        print()

    print(f"Done. lancedb written to: {LANCEDB_PATH}")
    print(f"Tables: {', '.join(ldb.list_tables())}")


if __name__ == "__main__":
    main()
