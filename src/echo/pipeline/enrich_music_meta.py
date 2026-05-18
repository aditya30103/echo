"""Last.fm music metadata enrichment (Tier 1 + Tier 2).

Adds genre + mood + locale tags to spotify_tracks rows, sourced from the
Last.fm community-tag vocabulary. Powers the new 5th lancedb table that
makes cross-modal queries possible ("when was I in a melancholy phase, and
what was I watching?"). See the Spotify Rework design doc for the full
shape.

Two tiers, mirroring the power-law shape of personal music libraries:
  Tier 1: artist.get_top_tags for every unique artist (~400-500 calls)
  Tier 2: track.get_top_tags for the top-N most-played tracks (default 500)

build_track_embed_text falls through Tier 2 -> Tier 1 -> name+artist only.

Inputs:  spotify_tracks (artist_name + track_name) + spotify_plays (counts)
Outputs: spotify_tracks.artist_lastfm_tags + spotify_tracks.lastfm_tags
         + spotify_tracks.meta_enriched_at

Idempotency: keyed by meta_enriched_at. Artists with at least one row whose
meta_enriched_at IS NULL are eligible; a successful run sets it on every
row for the artist (so the next run skips). Misses (Last.fm has no data
for this artist) also set meta_enriched_at to now and leave
artist_lastfm_tags=NULL so we don't re-fetch on every run.

External deps: LASTFM_API_KEY in ~/.echo/.env.
If unset, run() prints a setup message and exits 0 (NOT sys.exit(1)) so
`echo run` continues to the next pipeline step. This divergence from
enrich_spotify is intentional: Last.fm enrichment is genuinely optional;
the rest of Echo's pipeline runs without it.

Usage:
    echo enrich-music-meta              # Tier 1 + Tier 2 (top-500 tracks)
    echo enrich-music-meta --top-n 1000 # deeper Tier 2 coverage
    echo enrich-music-meta --top-n 0    # Tier 1 only, skip Tier 2
    echo enrich-music-meta --dry-run    # show counts, no API calls
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

import pylast
import sqlite_utils

from echo.config import EchoConfig, load_config

# Persist every N artist enrichments. Smaller = better resilience under
# crash / SIGINT / network drop; larger = fewer SQLite writes. 50 mirrors
# enrich_spotify.BATCH_FLUSH_EVERY (commit f333bc6) so both pipeline
# modules behave the same way under failure.
BATCH_FLUSH_EVERY = 50

# Retry budget for transient Last.fm rate-limit / 503 responses BEFORE we
# write a permanent miss row. Without this, a transient 429 would mark the
# artist as a permanent miss requiring an unbuilt --refresh-misses flag.
MAX_RETRIES = 3
RETRY_BASE_WAIT_SEC = 5  # exponential: 5, 10, 20

# Last.fm WSError.status codes worth retrying. From pylast.WSError docstring.
PYLAST_STATUS_RATE_LIMIT = "29"           # STATUS_RATE_LIMIT_EXCEEDED
PYLAST_STATUS_TEMPORARILY_UNAVAILABLE = "16"


# ── Schema ──────────────────────────────────────────────────────────────────

def init_schema(db: sqlite_utils.Database) -> None:
    """Add the 3 music-meta columns to spotify_tracks if missing.

    Idempotent — safe to call from echo run on every invocation. Creates
    the base spotify_tracks table too (matches enrich_spotify.init_schema)
    so this module can be run even if enrich-spotify never has.
    """
    db.execute("""
        CREATE TABLE IF NOT EXISTS spotify_tracks (
            spotify_track_uri TEXT PRIMARY KEY,
            track_name        TEXT,
            artist_name       TEXT,
            duration_ms       INTEGER,
            explicit          INTEGER,
            uri_verified      INTEGER NOT NULL DEFAULT 0,
            fetched_at        TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    cols = {row[1] for row in db.execute("PRAGMA table_info(spotify_tracks)")}
    if "artist_lastfm_tags" not in cols:
        db.execute("ALTER TABLE spotify_tracks ADD COLUMN artist_lastfm_tags TEXT")
    if "lastfm_tags" not in cols:
        db.execute("ALTER TABLE spotify_tracks ADD COLUMN lastfm_tags TEXT")
    if "meta_enriched_at" not in cols:
        db.execute("ALTER TABLE spotify_tracks ADD COLUMN meta_enriched_at TEXT")


# ── Embedding text helper ───────────────────────────────────────────────────

def build_track_embed_text(
    track_name: str,
    artist_name: str,
    lastfm_tags: Sequence[str] | None,
    artist_lastfm_tags: Sequence[str] | None,
) -> str:
    """Compose the embedding-input string for one spotify_tracks row.

    Track-level tags win over artist-level (Tier 2 over Tier 1). Empty list
    and None both mean "no tags" — no `tags:` clause is emitted. Caller
    guarantees track_name + artist_name are non-empty strings.
    """
    parts = [f"{track_name} by {artist_name}"]
    tags = list(lastfm_tags) if lastfm_tags else (list(artist_lastfm_tags) if artist_lastfm_tags else [])
    if tags:
        seen: set[str] = set()
        kept: list[str] = []
        for t in tags:
            if t not in seen:
                seen.add(t)
                kept.append(t)
        parts.append(f"tags: {', '.join(kept)}")
    return " - ".join(parts)


# ── Retry helper ────────────────────────────────────────────────────────────

def _is_rate_limited(e: pylast.WSError) -> bool:
    return getattr(e, "status", None) in (
        PYLAST_STATUS_RATE_LIMIT,
        PYLAST_STATUS_TEMPORARILY_UNAVAILABLE,
    )


def _call_with_retry(fn: Callable[[], Any], *, max_retries: int = MAX_RETRIES) -> Any:
    """Retry rate-limit / temporary failures; let other pylast errors propagate.

    Used as a wrapper around pylast network calls so a transient 429 doesn't
    get permanently written as a NULL-tag miss.
    """
    for attempt in range(max_retries):
        try:
            return fn()
        except pylast.WSError as e:
            if _is_rate_limited(e) and attempt < max_retries - 1:
                wait = RETRY_BASE_WAIT_SEC * (2 ** attempt)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("retry loop exhausted without raising")  # unreachable


# ── Tier 1: per-artist enrichment ───────────────────────────────────────────

def _tier1(db: sqlite_utils.Database, network: pylast.LastFMNetwork) -> int:
    """Enrich every artist with at least one un-meta-enriched spotify_tracks row.

    Returns the count of artist enrichments written (one per artist, not per
    row). UPDATE WHERE artist_name = ? broadcasts the artist's tags to every
    row Spotify has surfaced for that artist.
    """
    artists = [row[0] for row in db.execute("""
        SELECT DISTINCT artist_name
        FROM spotify_tracks
        WHERE artist_name IS NOT NULL
          AND artist_name != ''
          AND meta_enriched_at IS NULL
        ORDER BY artist_name
    """)]

    total = len(artists)
    if total == 0:
        print("      Tier 1: all artists already enriched.")
        return 0

    print(f"      Tier 1: {total} artists to enrich")

    pending_updates: list[tuple[str | None, str, str]] = []
    written = 0
    miss_count = 0
    report_every = max(1, total // 20)

    def _flush() -> int:
        nonlocal pending_updates
        if not pending_updates:
            return 0
        n = len(pending_updates)
        # Transactional batch: cuts per-batch fsync from N to 1.
        with db.conn:
            db.conn.executemany(
                "UPDATE spotify_tracks "
                "SET artist_lastfm_tags = ?, meta_enriched_at = ? "
                "WHERE artist_name = ?",
                pending_updates,
            )
        pending_updates = []
        return n

    try:
        for i, artist_name in enumerate(artists, 1):
            tags_json: str | None = None  # NULL marks a permanent miss
            try:
                artist = network.get_artist(artist_name)
                top_items = _call_with_retry(lambda: artist.get_top_tags(limit=10))
                tags = [item.item.get_name() for item in top_items]
                # Dedupe preserving order. Last.fm occasionally returns
                # duplicate tag names from different community sources.
                seen: set[str] = set()
                deduped: list[str] = []
                for tag in tags:
                    if tag not in seen:
                        seen.add(tag)
                        deduped.append(tag)
                tags_json = json.dumps(deduped, ensure_ascii=False)
            except pylast.WSError:
                miss_count += 1
                # tags_json stays None; meta_enriched_at still set below so
                # we don't pound Last.fm with the same miss every run.

            now = datetime.now(timezone.utc).isoformat()
            pending_updates.append((tags_json, now, artist_name))

            if i % BATCH_FLUSH_EVERY == 0:
                written += _flush()

            if i % report_every == 0 or i == total:
                pct = round(i / total * 100)
                print(f"      [{pct:3d}%] Tier 1: {i}/{total}  misses={miss_count}")
    finally:
        # finally guarantees partial progress lands on any exception path
        # (KeyboardInterrupt, network drop, etc.) — mirrors enrich_spotify.
        written += _flush()
        print(f"      Tier 1: +{written} artist enrichments written, {miss_count} misses")

    return written


# ── Tier 2: per-track enrichment for top-N most-played ──────────────────────

def _tier2(db: sqlite_utils.Database, network: pylast.LastFMNetwork, top_n: int) -> int:
    """Enrich the top-N most-played tracks with Last.fm track-level tags.

    Skipped entirely when top_n=0. Only considers tracks that are in
    spotify_tracks (have been Spotify-enriched) AND don't yet have
    lastfm_tags. On WSError / 0-tags, writes "[]" so subsequent runs
    don't re-attempt — Tier 2 misses are absorbed silently because
    build_track_embed_text falls back to artist_lastfm_tags.

    Returns the count of track enrichments written.
    """
    if top_n <= 0:
        print("      Tier 2: skipped (top_n=0).")
        return 0

    # Tracks that are in spotify_tracks AND have non-null name/artist AND
    # haven't been Tier 2'd yet. Joined with play counts from spotify_plays
    # so we process the most-played first.
    tracks = list(db.execute("""
        SELECT t.spotify_track_uri,
               t.track_name,
               t.artist_name,
               p.plays
        FROM spotify_tracks t
        JOIN (
            SELECT spotify_track_uri, COUNT(*) AS plays
            FROM spotify_plays
            WHERE content_type = 'track' AND spotify_track_uri IS NOT NULL
            GROUP BY spotify_track_uri
        ) p ON t.spotify_track_uri = p.spotify_track_uri
        WHERE t.track_name IS NOT NULL AND t.track_name != ''
          AND t.artist_name IS NOT NULL AND t.artist_name != ''
          AND t.lastfm_tags IS NULL
        ORDER BY p.plays DESC
        LIMIT ?
    """, [top_n]))

    total = len(tracks)
    if total == 0:
        print("      Tier 2: all top tracks already enriched.")
        return 0

    print(f"      Tier 2: {total} tracks to enrich (top-{top_n})")

    pending_updates: list[tuple[str, str, str]] = []
    written = 0
    miss_count = 0
    report_every = max(1, total // 20)

    def _flush() -> int:
        nonlocal pending_updates
        if not pending_updates:
            return 0
        n = len(pending_updates)
        with db.conn:
            db.conn.executemany(
                "UPDATE spotify_tracks "
                "SET lastfm_tags = ?, meta_enriched_at = ? "
                "WHERE spotify_track_uri = ?",
                pending_updates,
            )
        pending_updates = []
        return n

    try:
        for i, (uri, track_name, artist_name, _plays) in enumerate(tracks, 1):
            tags_json: str = "[]"  # Tier 2 misses write empty array, not NULL
            try:
                track = network.get_track(artist_name, track_name)
                top_items = _call_with_retry(lambda: track.get_top_tags(limit=10))
                tags = [item.item.get_name() for item in top_items]
                seen: set[str] = set()
                deduped: list[str] = []
                for tag in tags:
                    if tag not in seen:
                        seen.add(tag)
                        deduped.append(tag)
                tags_json = json.dumps(deduped, ensure_ascii=False)
            except pylast.WSError:
                miss_count += 1
                # tags_json stays "[]" so the next run's discovery query
                # (lastfm_tags IS NULL) excludes this URI.

            now = datetime.now(timezone.utc).isoformat()
            pending_updates.append((tags_json, now, uri))

            if i % BATCH_FLUSH_EVERY == 0:
                written += _flush()

            if i % report_every == 0 or i == total:
                pct = round(i / total * 100)
                print(f"      [{pct:3d}%] Tier 2: {i}/{total}  misses={miss_count}")
    finally:
        written += _flush()
        print(f"      Tier 2: +{written} track enrichments written, {miss_count} misses")

    return written


# ── Entry point ─────────────────────────────────────────────────────────────

def run(config: EchoConfig, dry_run: bool = False, top_n: int = 500) -> None:
    """Enrich spotify_tracks with Last.fm tags. Tier 1 only in this phase.

    Args:
        config:  EchoConfig. Uses config.db_path + config.api_keys.lastfm.
        dry_run: If True, print pending counts and return without API calls.
        top_n:   Tier 2 depth (Phase C; unused here, accepted for stable API).
    """
    api_key = config.api_keys.lastfm or ""
    if not api_key:
        # Fail-soft: echo run continues past this step.
        print("LASTFM_API_KEY not set; skipping music metadata enrichment.")
        print("Get a free key at last.fm/api/account/create and add to ~/.echo/.env")
        print("to unlock the mood/genre dimension. Continuing pipeline...")
        return

    config.data_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite_utils.Database(config.db_path)
    init_schema(db)

    # spotify_plays is created by ingest.py. If it doesn't exist, we have
    # nothing to enrich - skip the entire module rather than crashing.
    if "spotify_plays" not in db.table_names():
        print("music_meta: spotify_plays not present; run `echo ingest` first.")
        print("Continuing pipeline...")
        return

    pending_tier1 = db.execute("""
        SELECT COUNT(DISTINCT artist_name)
        FROM spotify_tracks
        WHERE artist_name IS NOT NULL
          AND artist_name != ''
          AND meta_enriched_at IS NULL
    """).fetchone()[0]
    pending_tier2 = db.execute("""
        SELECT COUNT(*)
        FROM spotify_tracks t
        JOIN (
            SELECT spotify_track_uri, COUNT(*) AS plays
            FROM spotify_plays
            WHERE content_type = 'track' AND spotify_track_uri IS NOT NULL
            GROUP BY spotify_track_uri
        ) p ON t.spotify_track_uri = p.spotify_track_uri
        WHERE t.track_name IS NOT NULL AND t.artist_name IS NOT NULL
          AND t.lastfm_tags IS NULL
    """).fetchone()[0]
    # Tier 2 actual work = min(pending_tier2, top_n)
    will_tier2 = 0 if top_n <= 0 else min(pending_tier2, top_n)

    print(f"music_meta: Tier 1 pending={pending_tier1} artists; "
          f"Tier 2 pending={pending_tier2} tracks, will process top {will_tier2}")

    if dry_run:
        print("[dry-run] no API calls made")
        return

    if pending_tier1 == 0 and will_tier2 == 0:
        print("Nothing to do.")
        return

    network = pylast.LastFMNetwork(api_key=api_key)
    # pylast does NOT auto-throttle by default. Without this, sequential
    # calls would burst above the published 5 req/s ceiling and get 429s.
    network.enable_rate_limit()

    _tier1(db, network)
    _tier2(db, network, top_n)

    enriched_artists = db.execute("""
        SELECT COUNT(DISTINCT artist_name)
        FROM spotify_tracks
        WHERE artist_lastfm_tags IS NOT NULL
    """).fetchone()[0]
    enriched_tracks = db.execute("""
        SELECT COUNT(*)
        FROM spotify_tracks
        WHERE lastfm_tags IS NOT NULL AND lastfm_tags != '[]'
    """).fetchone()[0]
    print()
    print(f"Done. Artists with tags: {enriched_artists}; tracks with track-level tags: {enriched_tracks}")


def main() -> None:
    """Legacy entry for `python -m echo.pipeline.enrich_music_meta [...]`."""
    parser = argparse.ArgumentParser(description="Enrich spotify_tracks via Last.fm")
    parser.add_argument("--dry-run", action="store_true", help="Show counts, no API calls")
    parser.add_argument("--top-n",   type=int, default=500, help="Tier 2 depth (Phase C)")
    args = parser.parse_args()
    run(load_config(), dry_run=args.dry_run, top_n=args.top_n)


if __name__ == "__main__":
    main()
