#!/usr/bin/env python3
"""
Echo — Spotify track enrichment via search API.

Fetches duration_ms and explicit flag for every unique spotify_track_uri in
spotify_plays using the /search endpoint (the only Spotify API endpoint
available to apps registered after November 2024).

Batch endpoints (/tracks, /artists) and audio features (/audio-features) are
all restricted for new apps. See DATA.md for the full column-level notes.

Search approach: query "track:{name} artist:{artist}" and verify that the
returned URI matches the URI we already have in spotify_plays. Mismatches
are flagged (uri_verified=0) but duration_ms is still stored.

Inputs:  spotify_plays (echo.db) — distinct spotify_track_uri values
Outputs: spotify_tracks (echo.db) — duration_ms, explicit, uri_verified,
         track_name, artist_name

Idempotency: keyed by spotify_track_uri. Already-enriched URIs are skipped;
safe to interrupt at any time and re-run later. Use --limit to test on a
small slice first.

External deps: SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET in .env
(Client Credentials flow — no user login needed). Register a free app
at https://developer.spotify.com/dashboard.

Quota: Spotify enforces a rolling per-app daily limit (not strictly
documented). SLEEP_SEC is set at 1.0s between requests; a full enrich
of ~4k tracks takes ~70 min. If Retry-After exceeds MAX_RETRY_WAIT_SEC
(120s) the script aborts cleanly — re-run later or rotate Client ID.

Usage:
    python enrich_spotify.py               # enrich all pending tracks
    python enrich_spotify.py --dry-run     # show counts, no API calls
    python enrich_spotify.py --limit 100   # enrich first N pending tracks

Requires in .env:
    SPOTIFY_CLIENT_ID=...
    SPOTIFY_CLIENT_SECRET=...
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx
import sqlite_utils

from echo.config import EchoConfig, load_config

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_SEARCH    = "https://api.spotify.com/v1/search"

# 1.0s between searches → 1 req/s, conservative against Spotify's daily quota.
# Debug/test runs can exhaust quota faster than the per-minute limit suggests —
# stay well under with a generous inter-request pause.
SLEEP_SEC = 1.0

# If Retry-After exceeds this, abort rather than hang. Quota reset is ~24h;
# re-run tomorrow (or with a fresh Client ID) rather than sleeping for hours.
MAX_RETRY_WAIT_SEC = 120

# Persist to spotify_tracks every N enriched rows. Trade-off: smaller = better
# crash/quota resilience, larger = fewer SQLite write transactions. At 50 rows
# and 1s/req, a flush happens every ~50s of API work — losing at most ~50
# tracks if the process is killed between flushes. Anything we persist will be
# skipped by the LEFT JOIN on the next run, giving free quasi-resume.
BATCH_FLUSH_EVERY = 50


# ── Schema ──────────────────────────────────────────────────────────────────

def init_schema(db: sqlite_utils.Database) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS spotify_tracks (
            spotify_track_uri   TEXT PRIMARY KEY,
            track_name          TEXT,
            artist_name         TEXT,
            duration_ms         INTEGER,
            explicit            INTEGER,
            uri_verified        INTEGER NOT NULL DEFAULT 0,
            fetched_at          TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # Add uri_verified if table was created by an older schema version
    cols = {row[1] for row in db.execute("PRAGMA table_info(spotify_tracks)")}
    if "uri_verified" not in cols:
        db.execute("ALTER TABLE spotify_tracks ADD COLUMN uri_verified INTEGER NOT NULL DEFAULT 0")


# ── Spotify auth ─────────────────────────────────────────────────────────────

class SpotifyClient:
    """Minimal httpx wrapper — Client Credentials flow, auto token refresh."""

    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id     = client_id
        self._client_secret = client_secret
        self._token: str    = ""
        self._token_expiry  = 0.0
        self._http          = httpx.Client(timeout=30)

    def _refresh(self) -> None:
        resp = self._http.post(
            SPOTIFY_TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self._client_id, self._client_secret),
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 3600) - 60

    def search(self, track_name: str, artist_name: str) -> dict | None:
        """Search for a track. Returns the first result item or None."""
        if time.time() >= self._token_expiry:
            self._refresh()

        q = f'track:"{track_name}" artist:"{artist_name}"'
        for attempt in range(3):
            resp = self._http.get(
                SPOTIFY_SEARCH,
                headers={"Authorization": f"Bearer {self._token}"},
                params={"q": q, "type": "track", "limit": 1},
            )
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "5"))
                if wait > MAX_RETRY_WAIT_SEC:
                    print(f"      [quota exhausted] Retry-After={wait}s (~{round(wait/3600,1)}h)")
                    print(f"      Spotify daily quota is reset. Re-run tomorrow or use a new Client ID.")
                    raise SystemExit(1)
                print(f"      [rate limit] waiting {wait}s…")
                time.sleep(wait)
                continue
            if resp.status_code == 401:
                self._token_expiry = 0
                continue
            if resp.status_code != 200:
                return None
            items = resp.json().get("tracks", {}).get("items") or []
            return items[0] if items else None
        return None

    def close(self) -> None:
        self._http.close()


# ── Main enrichment ──────────────────────────────────────────────────────────

def enrich(db: sqlite_utils.Database, client: SpotifyClient, limit: int | None) -> None:
    # Unique (uri, track_name, artist_name) not yet in spotify_tracks
    pending: list[tuple[str, str, str]] = [
        (row[0], row[1] or "", row[2] or "")
        for row in db.execute("""
            SELECT DISTINCT p.spotify_track_uri, p.track_name, p.artist_name
            FROM spotify_plays p
            LEFT JOIN spotify_tracks t ON p.spotify_track_uri = t.spotify_track_uri
            WHERE p.content_type = 'track'
              AND p.spotify_track_uri IS NOT NULL
              AND t.spotify_track_uri IS NULL
            ORDER BY p.spotify_track_uri
        """)
    ]

    if limit:
        pending = pending[:limit]

    total = len(pending)
    if total == 0:
        print("      All tracks already enriched.")
        return

    print(f"      {total} tracks to enrich via search (~{round(total * SLEEP_SEC / 60, 1)} min)")

    rows: list[dict]  = []
    written           = 0
    verified          = 0
    unverified        = 0
    not_found         = 0
    report_every      = max(1, total // 20)  # progress every 5%

    def _flush() -> int:
        """Persist whatever's in `rows`, clear it, return how many were written.

        Called periodically and from the finally block, so a quota / network /
        SIGINT failure mid-loop never throws away enrichment progress. The
        next run's LEFT JOIN against spotify_tracks naturally skips anything
        already persisted (quasi-resume for free).
        """
        nonlocal rows
        if not rows:
            return 0
        n = len(rows)
        db["spotify_tracks"].insert_all(rows, replace=True)
        rows = []
        return n

    try:
        for i, (uri, track_name, artist_name) in enumerate(pending, 1):
            result = client.search(track_name, artist_name)
            time.sleep(SLEEP_SEC)

            if result is None:
                not_found += 1
                rows.append({
                    "spotify_track_uri": uri,
                    "track_name":        track_name or None,
                    "artist_name":       artist_name or None,
                    "duration_ms":       None,
                    "explicit":          None,
                    "uri_verified":      0,
                })
            else:
                matched = result.get("uri") == uri
                if matched:
                    verified += 1
                else:
                    unverified += 1

                rows.append({
                    "spotify_track_uri": uri,
                    "track_name":        result.get("name") or track_name or None,
                    "artist_name":       (result["artists"][0]["name"] if result.get("artists") else None) or artist_name or None,
                    "duration_ms":       result.get("duration_ms"),
                    "explicit":          int(bool(result.get("explicit"))),
                    "uri_verified":      int(matched),
                })

            if i % BATCH_FLUSH_EVERY == 0:
                written += _flush()

            if i % report_every == 0 or i == total:
                pct = round(i / total * 100)
                print(f"      [{pct:3d}%] {i}/{total}  verified={verified}  unverified={unverified}  not_found={not_found}")
    finally:
        leftover = _flush()
        written += leftover
        print(f"      +{written} rows written to spotify_tracks")


# ── CLI ──────────────────────────────────────────────────────────────────────

def run(config: EchoConfig, dry_run: bool = False, limit: int | None = None) -> None:
    """Enrich spotify_plays with track metadata via the Spotify search API.

    Args:
        config:  EchoConfig (uses config.db_path, config.api_keys.spotify_*).
        dry_run: If True, prints the pending count and exits without API calls.
        limit:   If set, enriches at most N pending tracks (useful for testing).
    """
    client_id     = config.api_keys.spotify_client_id or ""
    client_secret = config.api_keys.spotify_client_secret or ""

    if not client_id or not client_secret:
        print(
            "ERROR: SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set.\n"
            "Run `echo init` to configure, or add them to ~/.echo/.env directly.\n"
            "Create a Spotify Developer app at developer.spotify.com/dashboard"
        )
        sys.exit(1)

    config.data_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite_utils.Database(config.db_path)
    init_schema(db)

    already = db.execute("SELECT COUNT(*) FROM spotify_tracks").fetchone()[0]
    pending = db.execute("""
        SELECT COUNT(DISTINCT p.spotify_track_uri)
        FROM spotify_plays p
        LEFT JOIN spotify_tracks t ON p.spotify_track_uri = t.spotify_track_uri
        WHERE p.content_type = 'track'
          AND p.spotify_track_uri IS NOT NULL
          AND t.spotify_track_uri IS NULL
    """).fetchone()[0]

    print(f"spotify_tracks: {already} already enriched, {pending} pending")

    if dry_run:
        print("[dry-run] no API calls made")
        return

    if pending == 0:
        print("Nothing to do.")
        return

    client = SpotifyClient(client_id, client_secret)
    try:
        enrich(db, client, limit=limit)
    finally:
        client.close()

    total_now      = db.execute("SELECT COUNT(*) FROM spotify_tracks").fetchone()[0]
    duration_ok    = db.execute("SELECT COUNT(*) FROM spotify_tracks WHERE duration_ms IS NOT NULL").fetchone()[0]
    uri_ok         = db.execute("SELECT COUNT(*) FROM spotify_tracks WHERE uri_verified = 1").fetchone()[0]

    print()
    print(f"Done. spotify_tracks: {total_now} total")
    print(f"  duration_ms filled : {duration_ok} ({round(duration_ok/total_now*100)}%)")
    print(f"  URI verified match : {uri_ok} ({round(uri_ok/total_now*100)}%)")


def main() -> None:
    """Legacy entry retained for `python -m echo.pipeline.enrich_spotify [--dry-run] [--limit N]`."""
    parser = argparse.ArgumentParser(description="Enrich spotify_plays via Spotify search API")
    parser.add_argument("--dry-run", action="store_true", help="Show pending count, no API calls")
    parser.add_argument("--limit",   type=int,            help="Enrich at most N pending tracks")
    args = parser.parse_args()
    run(load_config(), dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
