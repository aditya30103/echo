#!/usr/bin/env python3
"""
Echo Layer 4 — Semantic search across reflections, videos, and searches.

Embeds a query string and returns nearest neighbours from lancedb.

Usage:
    python query.py "when was I most anxious about the future"
    python query.py --table reflections "transition and identity"
    python query.py --table videos "mathematics and proof"
    python query.py --table searches "career and uncertainty"
    python query.py --top 10 "late night studying"
    python query.py --table reflections --top 3 "military and discipline"
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import lancedb

BASE         = Path(__file__).parent
ENV_PATH     = BASE / ".env"
LANCEDB_PATH = BASE / "lancedb"

OPENAI_EMBED_MODEL     = "text-embedding-3-small"
OPENROUTER_EMBED_MODEL = "openai/text-embedding-3-small"

ALL_TABLES = ["reflections", "videos", "searches"]


# ── Env / API ─────────────────────────────────────────────────────────────────

def load_env():
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def get_embed_client():
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

    print("ERROR: No API key found. Set OPENAI_API_KEY or OPENROUTER_API_KEY in .env")
    sys.exit(1)


def embed_query(client, model: str, text: str) -> list[float]:
    response = client.embeddings.create(model=model, input=[text])
    return response.data[0].embedding


# ── Formatting ────────────────────────────────────────────────────────────────

def fmt_month_year(date_str: str) -> str:
    """'2020-07-13' -> 'Jul 2020'"""
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d").strftime("%b %Y")
    except Exception:
        return date_str[:7]


def fmt_date_range(start: str, end: str) -> str:
    s, e = fmt_month_year(start), fmt_month_year(end)
    return s if s == e else f"{s} – {e}"


def sim_pct(distance: float) -> str:
    """Convert lancedb cosine distance (1 - similarity) to a readable percentage."""
    return f"{(1 - distance) * 100:.0f}%"


def truncate(text: str, width: int = 120) -> str:
    text = text.replace("\n", " ").strip()
    return text[:width] + "…" if len(text) > width else text


# ── Result printers ───────────────────────────────────────────────────────────

def print_reflections(results: list[dict]):
    print(f"\n{'─' * 58}")
    print("  REFLECTIONS  (chapter arc)")
    print(f"{'─' * 58}")
    if not results:
        print("  (no results)")
        return
    for i, r in enumerate(results, 1):
        date_range = fmt_date_range(r.get("start_at", ""), r.get("end_at", ""))
        score      = sim_pct(r["_distance"])
        ch         = r.get("chapter_id", "?")
        print(f"\n  {i}.  Ch {ch:>2}  ·  {date_range}  ·  sim {score}")
        print(f"      {truncate(r.get('text', ''), 140)}")


def print_videos(results: list[dict]):
    print(f"\n{'─' * 58}")
    print("  VIDEOS  (watch history)")
    print(f"{'─' * 58}")
    if not results:
        print("  (no results)")
        return
    for i, r in enumerate(results, 1):
        score   = sim_pct(r["_distance"])
        title   = r.get("title", r.get("text", "?"))
        channel = r.get("channel", "")
        count   = r.get("watch_count", 0)
        channel_str = f"  ·  {channel}" if channel else ""
        print(f"\n  {i}.  {truncate(title, 70)}{channel_str}")
        print(f"      watched {count}×  ·  sim {score}")


def print_searches(results: list[dict]):
    print(f"\n{'─' * 58}")
    print("  SEARCHES  (YouTube query history)")
    print(f"{'─' * 58}")
    if not results:
        print("  (no results)")
        return
    for i, r in enumerate(results, 1):
        score      = sim_pct(r["_distance"])
        query      = r.get("query", r.get("text", "?"))
        count      = r.get("count", 0)
        first_seen = r.get("first_seen", "")
        last_seen  = r.get("last_seen", "")
        span       = f"{fmt_month_year(first_seen)} – {fmt_month_year(last_seen)}" if first_seen else ""
        span_str   = f"  ·  {span}" if span else ""
        print(f"\n  {i}.  \"{query}\"")
        print(f"      searched {count}×{span_str}  ·  sim {score}")


PRINTERS = {
    "reflections": print_reflections,
    "videos":      print_videos,
    "searches":    print_searches,
}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_env()

    parser = argparse.ArgumentParser(description="Echo semantic search")
    parser.add_argument("query",   help="Natural language query string")
    parser.add_argument("--table", choices=ALL_TABLES, help="Search one table only (default: all)")
    parser.add_argument("--top",   type=int, default=5, metavar="N", help="Results per table (default: 5)")
    args = parser.parse_args()

    if not LANCEDB_PATH.exists():
        print("ERROR: lancedb/ not found. Run embed.py first.")
        sys.exit(1)

    ldb            = lancedb.connect(str(LANCEDB_PATH))
    available      = ldb.list_tables().tables
    tables_to_search = [args.table] if args.table else ALL_TABLES

    client, model = get_embed_client()
    query_vector  = embed_query(client, model, args.query)

    print(f'\nQuery: "{args.query}"')

    for table_name in tables_to_search:
        if table_name not in available:
            print(f"\n  [{table_name}] not in lancedb — run embed.py first.")
            continue

        table   = ldb.open_table(table_name)
        results = (
            table.search(query_vector)
            .metric("cosine")
            .limit(args.top)
            .to_list()
        )
        PRINTERS[table_name](results)

    print()


if __name__ == "__main__":
    main()
