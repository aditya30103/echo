#!/usr/bin/env python3
"""
Echo enrichment — YouTube Data API v3.

Fetches category, duration, and tags for every distinct video_id in the
watches table. video_metadata acts as a persistent cache — already-fetched
IDs are skipped, so this script is safe to interrupt at any time.

Inputs:  watches (echo.db)
Outputs: video_metadata (echo.db)

Idempotency: keyed by video_id. Re-running spends no quota on already
enriched videos. Add a new Takeout, re-run ingest.py, re-run enrich.py
— only the new video_ids hit the API.

External deps: YOUTUBE_API_KEY in .env (or --key argument).
Get one free at: https://console.cloud.google.com/apis/credentials

Quota: 10,000 units / day on the free tier. `videos.list` costs 1 unit per
50 videos returned, so ~120 units enriches ~6,000 watches. On HTTP 403
quotaExceeded the script exits cleanly with a message — re-run after the
midnight Pacific reset.

Usage:
    $env:YOUTUBE_API_KEY = "YOUR_KEY"
    python enrich.py

    # or pass directly:
    python enrich.py --key YOUR_KEY
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
import sqlite_utils

from echo.config import EchoConfig, load_config

API_URL    = "https://www.googleapis.com/youtube/v3/videos"
BATCH_SIZE = 50      # YouTube API max per request
SLEEP_SEC  = 0.15    # ~6 req/s — well within quota, avoids bursting

# YouTube category ID → name mapping (stable set, rarely changes)
CATEGORY_NAMES = {
    1:  "Film & Animation",
    2:  "Autos & Vehicles",
    10: "Music",
    15: "Pets & Animals",
    17: "Sports",
    18: "Short Movies",
    19: "Travel & Events",
    20: "Gaming",
    21: "Videoblogging",
    22: "People & Blogs",
    23: "Comedy",
    24: "Entertainment",
    25: "News & Politics",
    26: "Howto & Style",
    27: "Education",
    28: "Science & Technology",
    29: "Nonprofits & Activism",
    30: "Movies",
    31: "Anime/Animation",
    32: "Action/Adventure",
    33: "Classics",
    34: "Comedy",
    35: "Documentary",
    36: "Drama",
    37: "Family",
    38: "Foreign",
    39: "Horror",
    40: "Sci-Fi/Fantasy",
    41: "Thriller",
    42: "Shorts",
    43: "Shows",
    44: "Trailers",
}

_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def parse_duration(iso: str) -> int:
    """Convert ISO 8601 duration string (e.g. PT4M13S) to seconds."""
    m = _DURATION_RE.match(iso or "")
    if not m:
        return 0
    h, mn, s = m.groups()
    return int(h or 0) * 3600 + int(mn or 0) * 60 + int(s or 0)


def fetch_batch(video_ids: list, api_key: str) -> dict:
    """
    Call videos.list for up to 50 IDs.
    Returns {video_id: row_dict} for videos that exist.
    IDs absent from the response are deleted or private.
    """
    resp = requests.get(
        API_URL,
        params={
            "part": "snippet,contentDetails",
            "id":   ",".join(video_ids),
            "key":  api_key,
        },
        timeout=30,
    )
    resp.raise_for_status()

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result = {}

    for item in resp.json().get("items", []):
        vid      = item["id"]
        snippet  = item.get("snippet", {})
        content  = item.get("contentDetails", {})
        cat_id   = int(snippet["categoryId"]) if snippet.get("categoryId") else None
        tags     = snippet.get("tags", [])

        result[vid] = {
            "video_id":         vid,
            "title":            snippet.get("title"),
            "channel_id":       snippet.get("channelId"),
            "channel_title":    snippet.get("channelTitle"),
            "category_id":      cat_id,
            "category_name":    CATEGORY_NAMES.get(cat_id) if cat_id else None,
            "duration_seconds": parse_duration(content.get("duration", "")),
            "tags":             json.dumps(tags[:20], ensure_ascii=False),
            "published_at":     snippet.get("publishedAt"),
            "fetched_at":       now,
            "available":        1,
        }

    return result


def run(config: EchoConfig, api_key_override: str | None = None) -> None:
    """Enrich watches with YouTube metadata.

    Args:
        config:           EchoConfig (uses config.db_path, config.api_keys.youtube).
        api_key_override: If provided, overrides config.api_keys.youtube (useful for
                          a one-off run with a different key).
    """
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    api_key = (api_key_override or config.api_keys.youtube or "").strip()
    if not api_key:
        print("ERROR: YouTube API key required.")
        print("  Set YOUTUBE_API_KEY in ~/.echo/.env, or run `echo init` to configure,")
        print("  or pass --key with `python -m echo.pipeline.enrich --key YOUR_KEY`.")
        sys.exit(1)

    config.data_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite_utils.Database(config.db_path)

    # Determine what still needs fetching
    already = {r[0] for r in db.execute("SELECT video_id FROM video_metadata").fetchall()}
    all_ids = [r[0] for r in db.execute("SELECT DISTINCT video_id FROM watches").fetchall()]
    todo    = [v for v in all_ids if v not in already]

    n_total   = len(all_ids)
    n_cached  = len(already)
    n_todo    = len(todo)
    n_batches = (n_todo + BATCH_SIZE - 1) // BATCH_SIZE if n_todo else 0

    print(f"Total unique video IDs:  {n_total:,}")
    print(f"Already in cache:        {n_cached:,}")
    print(f"To fetch:                {n_todo:,}  ({n_batches} API requests)")
    print(f"Quota cost:              {n_batches} units  "
          f"(of your 10,000 daily free)")
    print()

    if not todo:
        print("All videos already enriched. Nothing to do.")
        _print_summary(db)
        return

    fetched = unavailable = errors = 0
    start = time.time()

    for i in range(0, n_todo, BATCH_SIZE):
        batch     = todo[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1

        try:
            results = fetch_batch(batch, api_key)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response else "?"
            print(f"\nHTTP {status} on batch {batch_num}: {e}")
            if status == 403:
                print("Quota exceeded or key invalid.")
                print("Re-run tomorrow to continue — the cache picks up where you left off.")
                break
            errors += 1
            time.sleep(2)
            continue
        except requests.RequestException as e:
            print(f"\nNetwork error on batch {batch_num}: {e}")
            errors += 1
            time.sleep(2)
            continue

        # Upsert available videos
        if results:
            db["video_metadata"].insert_all(results.values(), replace=True)
            fetched += len(results)

        # Mark missing IDs as unavailable (deleted or private)
        for vid in set(batch) - set(results.keys()):
            db["video_metadata"].insert({
                "video_id":   vid,
                "available":  0,
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }, replace=True)
            unavailable += 1

        # Progress bar
        pct  = batch_num * 100 // n_batches
        bar  = "█" * (pct // 5) + "░" * (20 - pct // 5)
        elapsed = time.time() - start
        eta = (elapsed / batch_num) * (n_batches - batch_num) if batch_num else 0
        print(
            f"\r  [{bar}] {pct:>3}%  "
            f"batch {batch_num}/{n_batches}  "
            f"fetched={fetched}  unavailable={unavailable}  "
            f"ETA {eta:.0f}s   ",
            end="", flush=True,
        )

        time.sleep(SLEEP_SEC)

    print("\n")
    print("=" * 54)
    print("ENRICHMENT COMPLETE")
    print("=" * 54)
    print(f"  Fetched:             {fetched:,}")
    print(f"  Unavailable:         {unavailable:,}  (deleted or private)")
    print(f"  Errors:              {errors:,}")
    print(f"  Time:                {time.time() - start:.0f}s")
    print()
    _print_summary(db)


def _print_summary(db):
    total_enriched = db.execute(
        "SELECT COUNT(*) FROM video_metadata WHERE available = 1"
    ).fetchone()[0]
    total_watches  = db.execute("SELECT COUNT(*) FROM watches").fetchone()[0]
    coverage       = total_enriched * 100 // total_watches if total_watches else 0
    print(f"Enrichment coverage: {total_enriched:,} / {total_watches:,} watches ({coverage}%)")

    print("\nYour watch history by category:")
    rows = db.execute("""
        SELECT
            COALESCE(vm.category_name, 'not yet enriched') AS category,
            COUNT(*)                                        AS watches,
            ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct
        FROM watches w
        LEFT JOIN video_metadata vm ON w.video_id = vm.video_id
        GROUP BY category
        ORDER BY watches DESC
        LIMIT 15
    """).fetchall()
    for cat, n, pct in rows:
        bar = "#" * int(pct // 2)
        print(f"  {n:>5}  {pct:>5.1f}%  {cat:<28}  {bar}")


def main() -> None:
    """Legacy entry retained for `python -m echo.pipeline.enrich [--key KEY]`."""
    parser = argparse.ArgumentParser(description="Enrich Echo watch history via YouTube API")
    parser.add_argument("--key", help="YouTube Data API v3 key (overrides config)")
    args = parser.parse_args()
    run(load_config(), api_key_override=args.key)


if __name__ == "__main__":
    main()
