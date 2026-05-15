#!/usr/bin/env python3
"""
Echo — Spotify track enrichment.

Fetches track metadata and artist genres for every unique spotify_track_uri
in spotify_plays, storing results in the spotify_tracks table.

Audio features (valence, energy, danceability, etc.) require a Spotify app
registered before November 2024. If unavailable, those columns are stored as
NULL and the script continues — all other data is still fetched.

Safe to interrupt and re-run: already-enriched URIs are skipped.

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
from embed_common import load_env

BASE    = Path(__file__).parent
DB_PATH = BASE / "echo.db"

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE  = "https://api.spotify.com/v1"

TRACK_BATCH_SIZE   = 50   # /tracks endpoint max
ARTIST_BATCH_SIZE  = 50   # /artists endpoint max
FEATURE_BATCH_SIZE = 100  # /audio-features endpoint max

# Pause between batch requests — Spotify has unofficial rate limits (~180 req/30s).
# 0.15s gives ~6 req/s, well within the limit. On 429, we respect Retry-After.
SLEEP_SEC = 0.15


# ── Schema ──────────────────────────────────────────────────────────────────

def init_schema(db: sqlite_utils.Database) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS spotify_tracks (
            spotify_track_uri   TEXT PRIMARY KEY,
            track_name          TEXT,
            artist_name         TEXT,
            artist_uri          TEXT,
            album_name          TEXT,
            duration_ms         INTEGER,
            popularity          INTEGER,
            explicit            INTEGER,
            genres              TEXT,
            valence             REAL,
            energy              REAL,
            danceability        REAL,
            tempo               REAL,
            acousticness        REAL,
            instrumentalness    REAL,
            loudness            REAL,
            speechiness         REAL,
            mode                INTEGER,
            musical_key         INTEGER,
            audio_features_available INTEGER NOT NULL DEFAULT 0,
            fetched_at          TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)


# ── Spotify auth ─────────────────────────────────────────────────────────────

class SpotifyClient:
    """Thin httpx wrapper — Client Credentials flow, auto token refresh."""

    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id     = client_id
        self._client_secret = client_secret
        self._token: str    = ""
        self._token_expiry  = 0.0
        self._http          = httpx.Client(timeout=30)

    def _refresh_token(self) -> None:
        resp = self._http.post(
            SPOTIFY_TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self._client_id, self._client_secret),
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        # Subtract 60s buffer from 3600s expiry
        self._token_expiry = time.time() + data.get("expires_in", 3600) - 60

    def _headers(self) -> dict:
        if time.time() >= self._token_expiry:
            self._refresh_token()
        return {"Authorization": f"Bearer {self._token}"}

    def get(self, path: str, params: dict | None = None) -> dict:
        """GET /v1/<path> with automatic retry on 429 and token refresh on 401."""
        url = f"{SPOTIFY_API_BASE}/{path}"
        for attempt in range(4):
            resp = self._http.get(url, headers=self._headers(), params=params)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", "5"))
                print(f"      [rate limit] waiting {wait}s…")
                time.sleep(wait)
                continue
            if resp.status_code == 401:
                self._token_expiry = 0  # force refresh
                continue
            return resp
        resp.raise_for_status()
        return resp

    def close(self) -> None:
        self._http.close()


# ── Batch fetchers ───────────────────────────────────────────────────────────

def fetch_tracks(client: SpotifyClient, uris: list[str]) -> dict[str, dict]:
    """Fetch track objects for a list of spotify:track:... URIs.

    Returns {uri: track_object}. Missing/unavailable tracks are omitted.
    """
    ids = [u.split(":")[-1] for u in uris]
    result = {}
    for i in range(0, len(ids), TRACK_BATCH_SIZE):
        batch_ids = ids[i : i + TRACK_BATCH_SIZE]
        batch_uris = uris[i : i + TRACK_BATCH_SIZE]
        resp = client.get("tracks", {"ids": ",".join(batch_ids)})
        if resp.status_code != 200:
            print(f"      [warn] /tracks returned {resp.status_code}, skipping batch")
            time.sleep(SLEEP_SEC)
            continue
        tracks = resp.json().get("tracks") or []
        for uri, track in zip(batch_uris, tracks):
            if track:
                result[uri] = track
        time.sleep(SLEEP_SEC)
    return result


def fetch_artists(client: SpotifyClient, artist_uris: list[str]) -> dict[str, dict]:
    """Fetch artist objects for a list of spotify:artist:... URIs.

    Returns {uri: artist_object}.
    """
    ids = [u.split(":")[-1] for u in artist_uris]
    result = {}
    for i in range(0, len(ids), ARTIST_BATCH_SIZE):
        batch_ids = ids[i : i + ARTIST_BATCH_SIZE]
        batch_uris = artist_uris[i : i + ARTIST_BATCH_SIZE]
        resp = client.get("artists", {"ids": ",".join(batch_ids)})
        if resp.status_code != 200:
            print(f"      [warn] /artists returned {resp.status_code}, skipping batch")
            time.sleep(SLEEP_SEC)
            continue
        artists = resp.json().get("artists") or []
        for uri, artist in zip(batch_uris, artists):
            if artist:
                result[uri] = artist
        time.sleep(SLEEP_SEC)
    return result


def fetch_audio_features(
    client: SpotifyClient, uris: list[str]
) -> tuple[dict[str, dict], bool]:
    """Attempt to fetch audio features. Returns ({uri: features}, available).

    available=False means the endpoint returned 403 (deprecated for this app).
    In that case the returned dict is empty.
    """
    ids = [u.split(":")[-1] for u in uris]
    result = {}
    available = True

    for i in range(0, len(ids), FEATURE_BATCH_SIZE):
        batch_ids = ids[i : i + FEATURE_BATCH_SIZE]
        batch_uris = uris[i : i + FEATURE_BATCH_SIZE]
        resp = client.get("audio-features", {"ids": ",".join(batch_ids)})
        if resp.status_code == 403:
            available = False
            return {}, False
        if resp.status_code != 200:
            print(f"      [warn] /audio-features returned {resp.status_code}, skipping batch")
            time.sleep(SLEEP_SEC)
            continue
        features_list = resp.json().get("audio_features") or []
        for uri, feat in zip(batch_uris, features_list):
            if feat:
                result[uri] = feat
        time.sleep(SLEEP_SEC)

    return result, available


# ── Main enrichment ──────────────────────────────────────────────────────────

def enrich(db: sqlite_utils.Database, client: SpotifyClient, limit: int | None) -> None:
    # Find all unique track URIs not yet enriched
    pending_uris: list[str] = [
        row[0]
        for row in db.execute("""
            SELECT DISTINCT p.spotify_track_uri
            FROM spotify_plays p
            LEFT JOIN spotify_tracks t ON p.spotify_track_uri = t.spotify_track_uri
            WHERE p.content_type = 'track'
              AND p.spotify_track_uri IS NOT NULL
              AND t.spotify_track_uri IS NULL
            ORDER BY p.spotify_track_uri
        """)
    ]

    if limit:
        pending_uris = pending_uris[:limit]

    total = len(pending_uris)
    if total == 0:
        print("      All tracks already enriched.")
        return

    print(f"      {total} tracks to enrich")

    # ── Step 1: fetch track metadata ────────────────────────────────────────
    print("      [1/3] Fetching track metadata…")
    track_data = fetch_tracks(client, pending_uris)
    print(f"            {len(track_data)}/{total} fetched")

    # ── Step 2: fetch artist genres ─────────────────────────────────────────
    print("      [2/3] Fetching artist genres…")
    artist_uris = list({
        track["artists"][0]["uri"]
        for track in track_data.values()
        if track.get("artists")
    })
    artist_data = fetch_artists(client, artist_uris)
    print(f"            {len(artist_data)} unique artists enriched")

    # ── Step 3: fetch audio features (may be unavailable) ───────────────────
    print("      [3/3] Fetching audio features…")
    feature_data, features_available = fetch_audio_features(client, list(track_data.keys()))
    if features_available:
        print(f"            {len(feature_data)} tracks with audio features")
    else:
        print("            [skip] 403 — audio features deprecated for this app (new app registration)")
        print("                   valence/energy/danceability/tempo columns will be NULL")

    # ── Assemble rows ────────────────────────────────────────────────────────
    rows = []
    for uri, track in track_data.items():
        artist_uri  = track["artists"][0]["uri"] if track.get("artists") else None
        artist_obj  = artist_data.get(artist_uri) if artist_uri else None
        genres      = json.dumps(artist_obj["genres"]) if artist_obj else None
        feat        = feature_data.get(uri) if features_available else None

        rows.append({
            "spotify_track_uri":          uri,
            "track_name":                 track.get("name"),
            "artist_name":                track["artists"][0]["name"] if track.get("artists") else None,
            "artist_uri":                 artist_uri,
            "album_name":                 track.get("album", {}).get("name"),
            "duration_ms":                track.get("duration_ms"),
            "popularity":                 track.get("popularity"),
            "explicit":                   int(bool(track.get("explicit"))),
            "genres":                     genres,
            "valence":                    feat.get("valence")          if feat else None,
            "energy":                     feat.get("energy")           if feat else None,
            "danceability":               feat.get("danceability")     if feat else None,
            "tempo":                      feat.get("tempo")            if feat else None,
            "acousticness":               feat.get("acousticness")     if feat else None,
            "instrumentalness":           feat.get("instrumentalness") if feat else None,
            "loudness":                   feat.get("loudness")         if feat else None,
            "speechiness":                feat.get("speechiness")      if feat else None,
            "mode":                       feat.get("mode")             if feat else None,
            "musical_key":                feat.get("key")              if feat else None,
            "audio_features_available":   int(features_available),
            "fetched_at":                 None,  # DEFAULT in schema
        })

    db["spotify_tracks"].insert_all(rows, replace=True)
    print(f"      +{len(rows)} rows written to spotify_tracks")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    load_env()

    parser = argparse.ArgumentParser(description="Enrich spotify_plays with Spotify API track metadata")
    parser.add_argument("--dry-run", action="store_true", help="Show pending count, no API calls")
    parser.add_argument("--limit",   type=int,            help="Enrich at most N pending tracks")
    args = parser.parse_args()

    client_id     = os.environ.get("SPOTIFY_CLIENT_ID", "")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        print(
            "ERROR: SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set in .env\n"
            "Create a Spotify Developer app at developer.spotify.com/dashboard\n"
            "then copy Client ID and Client Secret into .env."
        )
        sys.exit(1)

    db = sqlite_utils.Database(DB_PATH)
    init_schema(db)

    pending = db.execute("""
        SELECT COUNT(DISTINCT p.spotify_track_uri)
        FROM spotify_plays p
        LEFT JOIN spotify_tracks t ON p.spotify_track_uri = t.spotify_track_uri
        WHERE p.content_type = 'track'
          AND p.spotify_track_uri IS NOT NULL
          AND t.spotify_track_uri IS NULL
    """).fetchone()[0]
    already = db.execute("SELECT COUNT(*) FROM spotify_tracks").fetchone()[0]

    print(f"spotify_tracks: {already} already enriched, {pending} pending")

    if args.dry_run:
        print("[dry-run] no API calls made")
        return

    if pending == 0:
        print("Nothing to do.")
        return

    client = SpotifyClient(client_id, client_secret)
    try:
        enrich(db, client, limit=args.limit)
    finally:
        client.close()

    total_now = db.execute("SELECT COUNT(*) FROM spotify_tracks").fetchone()[0]
    genres_filled = db.execute(
        "SELECT COUNT(*) FROM spotify_tracks WHERE genres IS NOT NULL AND genres != '[]'"
    ).fetchone()[0]
    duration_filled = db.execute(
        "SELECT COUNT(*) FROM spotify_tracks WHERE duration_ms IS NOT NULL"
    ).fetchone()[0]
    print()
    print(f"Done. spotify_tracks: {total_now} total")
    print(f"  duration_ms filled: {duration_filled}")
    print(f"  genres filled:      {genres_filled}")


if __name__ == "__main__":
    main()
