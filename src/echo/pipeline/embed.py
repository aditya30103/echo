#!/usr/bin/env python3
"""
Echo Layer 4 — Semantic embeddings into LanceDB.

Embeds four corpora (see ALL_TABLES in embed_common.py) into a local
LanceDB at ./lancedb/. The agent's `vector_search` tool reads from these
tables — a stale lancedb is the most common reason recent reflections
or new searches are missing from agent answers.

Corpora:
  - reflections     : chapter narratives (for arc-level semantic search)
  - videos          : unique video titles + channel (for content-level search)
  - searches        : unique YouTube search queries (for intent-level search)
  - google_searches : unique Google search queries (cross-platform intent)

Inputs:  reflections, watches+video_metadata, yt_searches, google_searches
         (echo.db)
Outputs: ./lancedb/ — 4 tables, each with text + a 1536-dim vector column

Model: text-embedding-3-small (1536 dims), via OpenAI direct or OpenRouter
(provider chosen by embed_common.get_embed_client).

Idempotency: drops and recreates each LanceDB table on every run. The
underlying ./lancedb/ directory is gitignored and fully regenerable
from echo.db, so blowing it away is safe.

Cost: ~$0.001-0.02 for a typical full embed run. text-embedding-3-small
is ~$0.02 per 1M tokens; ~10k texts × ~50 tokens each ≈ 500k tokens =
~$0.01 per full re-embed of the default 4 corpora.

Usage:
    python embed.py              # embed all four tables
    python embed.py --dry-run    # show counts and sample texts, no API calls
    python embed.py --table reflections   # embed one table only
    python embed.py --table videos
    python embed.py --table searches
    python embed.py --table google_searches
"""

import argparse
import sys
from pathlib import Path

import lancedb
import sqlite_utils

from echo.config import ALL_TABLES, EchoConfig, get_embed_client, load_config

EMBED_DIMS = 1536

BATCH_SIZE = 512  # inputs per embeddings API request; OpenAI hard limit is 2048


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
    # max_rewatch_count: highest rewatch count for this video across all sessions.
    rows = db.execute("""
        SELECT
            w.video_id,
            COALESCE(vm.title, w.title, w.video_id)   AS title,
            COALESCE(vm.channel_title, '')             AS channel,
            COUNT(*)                                   AS watch_count,
            COALESCE(MAX(ws.rewatch_count), 0)         AS max_rewatch_count
        FROM watches w
        LEFT JOIN video_metadata vm ON w.video_id = vm.video_id
        LEFT JOIN watch_signals ws  ON ws.watch_id  = w.id
        GROUP BY w.video_id
        ORDER BY watch_count DESC
    """).fetchall()
    records = []
    for video_id, title, channel, watch_count, max_rewatch_count in rows:
        text = f"{title} | {channel}" if channel else title
        records.append({
            "video_id":          video_id,
            "title":             title,
            "channel":           channel,
            "watch_count":       watch_count,
            "max_rewatch_count": max_rewatch_count,
            "text":              text,
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


def load_google_searches(db: sqlite_utils.Database) -> list[dict]:
    rows = db.execute("""
        SELECT query, COUNT(*) AS n,
               MIN(date(searched_at)) AS first_seen,
               MAX(date(searched_at)) AS last_seen
        FROM google_searches
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
    if name in ldb.list_tables().tables:
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

def run(config: EchoConfig, dry_run: bool = False, table: str | None = None) -> None:
    """Embed configured corpora into LanceDB.

    Args:
        config:  EchoConfig (uses config.db_path, config.lancedb_path,
                 config.api_keys.openai / config.api_keys.openrouter).
        dry_run: Show counts + sample texts, make no API calls.
        table:   If provided, embed only this table (one of ALL_TABLES).
    """
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    tables_to_run = [table] if table else ALL_TABLES

    config.data_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite_utils.Database(config.db_path)

    loaders = {
        "reflections":    load_reflections,
        "videos":         load_videos,
        "searches":       load_searches,
        "google_searches": load_google_searches,
    }
    datasets = {name: loaders[name](db) for name in tables_to_run}

    SEP = "=" * 60
    print(f"{SEP}\nECHO LAYER 4 - EMBEDDINGS\n{SEP}\n")

    if dry_run:
        for name, records in datasets.items():
            print(f"{name}: {len(records)} items")
            for rec in records[:3]:
                print(f"  sample: {rec['text'][:80]}")
            print()
        return

    client, model = get_embed_client()
    print(f"Provider: {model}\n")

    ldb = lancedb.connect(str(config.lancedb_path))

    for name, records in datasets.items():
        print(f"-- {name} --")
        if not records:
            print(f"  No data found - skipping.")
            continue
        texts   = [r["text"] for r in records]
        vectors = embed_all(client, model, texts, name)
        write_table(ldb, name, records, vectors)
        print()

    print(f"Done. lancedb written to: {config.lancedb_path}")
    print(f"Tables: {', '.join(ldb.list_tables().tables)}")


def main() -> None:
    """Legacy entry retained for `python -m echo.pipeline.embed [--dry-run] [--table NAME]`."""
    parser = argparse.ArgumentParser(description="Echo Layer 4 - semantic embeddings")
    parser.add_argument("--dry-run", action="store_true", help="Show counts, no API calls")
    parser.add_argument("--table",   choices=ALL_TABLES,  help="Embed one table only")
    args = parser.parse_args()
    run(load_config(), dry_run=args.dry_run, table=args.table)


if __name__ == "__main__":
    main()
