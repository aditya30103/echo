#!/usr/bin/env python3
"""
Echo Layer 1 — Takeout + Spotify ingestion into echo.db.

The first stage in the pipeline. Reads raw archive files from `_data/` and
writes one row per source event into typed SQLite tables. Every later
script reads what ingest.py wrote — nothing depends on a later stage.

Inputs (all in _data/, paths configurable near the top of the file):
    YouTube Takeout zip      -> watches, yt_searches, watch_later
    Google My Activity zip   -> google_searches, discover_feed
    Calendar Takeout zip     -> calendar_events
    Spotify Extended History -> spotify_plays  (optional; missing zip
                                                skipped with a notice)

Outputs (tables in echo.db, created on demand):
    watches, yt_searches, watch_later, google_searches, discover_feed,
    calendar_events, transactions, spotify_plays

Idempotency: every table has a UNIQUE constraint on its natural key
(video_id+watched_at, query+searched_at, etc.). Safe to re-run after
dropping a new Takeout / Spotify export into `_data/` — only new rows
are inserted; duplicates silently fall away.

Cost: zero (no API calls, pure local file processing).
Runtime: ~5-15s for typical exports (~6k watches + ~17k Spotify plays).

Run:
    python ingest.py
"""

import csv
import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import sqlite_utils

# ── Paths ──────────────────────────────────────────────────────────────────
BASE = Path(__file__).parent
DB_PATH = BASE / "echo.db"

# Raw source archives live in `_data/` (gitignored) — keeps the repo root tidy
# and shields ~340MB of personal data from accidental `git add`. Replace these
# filenames with whatever Google Takeout / Spotify named YOUR exports.
DATA_DIR     = BASE / "_data"
ZIP_YT       = DATA_DIR / "takeout-20260512T160253Z-4-001.zip"   # YouTube Takeout
ZIP_ACTIVITY = DATA_DIR / "takeout-20260512T160253Z-6-001.zip"   # My Activity
ZIP_CALENDAR = DATA_DIR / "takeout-20260512T161750Z-3-001.zip"   # Calendar
# SPOTIFY_ZIP: place my_spotify_data.zip in _data/, or override via env var
ZIP_SPOTIFY  = DATA_DIR / os.environ.get("SPOTIFY_ZIP", "my_spotify_data.zip")


# ── Timestamp helpers ───────────────────────────────────────────────────────
def to_utc(ts: str) -> str:
    """Normalize any ISO8601 timestamp to UTC with +00:00 suffix."""
    if not ts:
        return ts
    if ts.endswith("Z"):
        return ts[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(ts)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return ts


# ── Schema ──────────────────────────────────────────────────────────────────
def init_schema(db: sqlite_utils.Database):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS watches (
            id          INTEGER PRIMARY KEY,
            video_id    TEXT NOT NULL,
            title       TEXT NOT NULL,
            channel_name TEXT,
            channel_id  TEXT,
            watched_at  TEXT NOT NULL,
            source      TEXT NOT NULL,
            UNIQUE(video_id, watched_at)
        );

        CREATE TABLE IF NOT EXISTS video_metadata (
            video_id        TEXT PRIMARY KEY,
            title           TEXT,
            channel_id      TEXT,
            channel_title   TEXT,
            category_id     INTEGER,
            category_name   TEXT,
            duration_seconds INTEGER,
            tags            TEXT,   -- JSON array
            published_at    TEXT,
            fetched_at      TEXT,
            available       INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS yt_searches (
            id          INTEGER PRIMARY KEY,
            query       TEXT NOT NULL,
            searched_at TEXT NOT NULL,
            UNIQUE(query, searched_at)
        );

        CREATE TABLE IF NOT EXISTS watch_later (
            video_id TEXT PRIMARY KEY,
            added_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS google_searches (
            id          INTEGER PRIMARY KEY,
            query       TEXT NOT NULL,
            searched_at TEXT NOT NULL,
            UNIQUE(query, searched_at)
        );

        CREATE TABLE IF NOT EXISTS discover_feed (
            id           INTEGER PRIMARY KEY,
            snapshot_at  TEXT NOT NULL,
            all_topics   TEXT NOT NULL,   -- JSON array
            viewed_topics TEXT NOT NULL,  -- JSON array (topics user clicked)
            UNIQUE(snapshot_at)
        );

        CREATE TABLE IF NOT EXISTS calendar_events (
            id            INTEGER PRIMARY KEY,
            calendar_name TEXT NOT NULL,
            summary       TEXT,
            start_date    TEXT NOT NULL,
            end_date      TEXT,
            created_at    TEXT
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id             INTEGER PRIMARY KEY,
            amount_inr     REAL NOT NULL,
            direction      TEXT NOT NULL,   -- 'sent' | 'received'
            transacted_at  TEXT NOT NULL,
            UNIQUE(amount_inr, direction, transacted_at)
        );

        -- Populated by Layer 2 (PELT changepoint detection)
        CREATE TABLE IF NOT EXISTS chapters (
            id       INTEGER PRIMARY KEY,
            start_at TEXT NOT NULL,
            end_at   TEXT NOT NULL,
            label    TEXT
        );

        CREATE TABLE IF NOT EXISTS chapter_fingerprints (
            chapter_id             INTEGER PRIMARY KEY REFERENCES chapters(id),
            top_categories         TEXT,   -- JSON {category: pct}
            median_duration_seconds REAL,
            modal_hour             INTEGER,
            channel_density_score  REAL,
            night_ratio            REAL,
            shorts_ratio           REAL,
            long_form_ratio        REAL
        );

        -- Populated by signals.py (engagement scoring)
        CREATE TABLE IF NOT EXISTS watch_signals (
            watch_id         INTEGER PRIMARY KEY REFERENCES watches(id),
            session_id       INTEGER NOT NULL,
            session_depth    INTEGER NOT NULL,
            session_length   INTEGER NOT NULL,
            is_rewatch       INTEGER NOT NULL DEFAULT 0,
            rewatch_count    INTEGER NOT NULL DEFAULT 1,
            is_search_driven INTEGER NOT NULL DEFAULT 0,
            is_autoplay      INTEGER NOT NULL DEFAULT 0,
            was_bookmarked   INTEGER NOT NULL DEFAULT 0
        );

        -- Populated by reflect.py (Layer 3 GPT-4o narrative reflection)
        CREATE TABLE IF NOT EXISTS reflections (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_id   INTEGER REFERENCES chapters(id),
            kind         TEXT NOT NULL,
            prompt_text  TEXT,
            reflection   TEXT,
            model        TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        );

        -- Populated by ingest.py (Spotify Extended Streaming History)
        CREATE TABLE IF NOT EXISTS spotify_plays (
            id                   INTEGER PRIMARY KEY,
            ts                   TEXT    NOT NULL,
            ms_played            INTEGER NOT NULL DEFAULT 0,
            track_name           TEXT,
            artist_name          TEXT,
            album_name           TEXT,
            spotify_track_uri    TEXT,
            episode_name         TEXT,
            episode_show_name    TEXT,
            spotify_episode_uri  TEXT,
            reason_start         TEXT,
            reason_end           TEXT,
            shuffle              INTEGER NOT NULL DEFAULT 0,
            skipped              INTEGER NOT NULL DEFAULT 0,
            offline              INTEGER NOT NULL DEFAULT 0,
            incognito_mode       INTEGER NOT NULL DEFAULT 0,
            platform             TEXT,
            conn_country         TEXT,
            content_type         TEXT    NOT NULL,
            source_file          TEXT
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_spotify_plays
            ON spotify_plays(ts, COALESCE(spotify_track_uri, spotify_episode_uri, ''));

        CREATE INDEX IF NOT EXISTS idx_watches_time    ON watches(watched_at);
        CREATE INDEX IF NOT EXISTS idx_watches_video   ON watches(video_id);
        CREATE INDEX IF NOT EXISTS idx_watches_channel ON watches(channel_name);
        DROP INDEX IF EXISTS idx_watches_hour;
        CREATE INDEX IF NOT EXISTS idx_watches_hour_ist
            ON watches(CAST(strftime('%H', datetime(watched_at, '+330 minutes')) AS INTEGER));
    """)

    # Deduplicate calendar_events from runs before UNIQUE index existed, then lock it.
    db.execute("""
        DELETE FROM calendar_events WHERE id NOT IN (
            SELECT MIN(id) FROM calendar_events
            GROUP BY calendar_name, COALESCE(summary, ''), start_date
        )
    """)
    db.conn.commit()
    db.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_calendar_unique
        ON calendar_events(calendar_name, COALESCE(summary, ''), start_date)
    """)

    # enriched_watches view: watches LEFT JOIN video_metadata with computed columns.
    # All hour/day calculations are in IST (UTC+5:30 = +330 minutes).
    # DROP first so re-runs pick up schema changes.
    db.execute("DROP VIEW IF EXISTS enriched_watches")
    db.execute("""
        CREATE VIEW enriched_watches AS
        SELECT
            w.id,
            w.video_id,
            w.title,
            w.channel_name,
            w.watched_at,
            w.source,
            CAST(substr(datetime(w.watched_at, '+330 minutes'), 12, 2) AS INTEGER)    AS hour_of_day_ist,
            CAST(strftime('%w', datetime(w.watched_at, '+330 minutes')) AS INTEGER)   AS day_of_week_ist,
            CASE
                WHEN CAST(substr(datetime(w.watched_at, '+330 minutes'), 12, 2) AS INTEGER) >= 22
                  OR CAST(substr(datetime(w.watched_at, '+330 minutes'), 12, 2) AS INTEGER) <  4
                THEN 1 ELSE 0
            END AS is_night,
            COALESCE(vm.category_name, 'unknown')                      AS category_name,
            COALESCE(vm.duration_seconds, 0)                           AS duration_seconds,
            CASE
                WHEN COALESCE(vm.duration_seconds, 0) >= 1200 THEN 'long'
                WHEN COALESCE(vm.duration_seconds, 0) >=  300 THEN 'medium'
                WHEN COALESCE(vm.duration_seconds, 0) >    0  THEN 'short'
                ELSE 'unknown'
            END AS duration_bucket,
            vm.available
        FROM watches w
        LEFT JOIN video_metadata vm ON w.video_id = vm.video_id
    """)


# ── Watch helpers ────────────────────────────────────────────────────────────
_VIDEO_ID_RE = re.compile(r"[?&]v=([A-Za-z0-9_-]{11})")
_CHANNEL_ID_RE = re.compile(r"/channel/([A-Za-z0-9_-]+)")
_WATCHED_PREFIX = ("Watched\u202f", "Watched ")  # \u202f = narrow no-break space (Google Takeout)


def _is_ad(entry: dict) -> bool:
    return any(d.get("name") == "From Google Ads" for d in entry.get("details", []))


def _strip_watched(title: str) -> str:
    for prefix in _WATCHED_PREFIX:
        if title.startswith(prefix):
            return title[len(prefix):]
    return title


def _parse_watch_rows(entries: list, source: str) -> tuple[list[dict], int, int]:
    rows, skipped_ads, skipped_no_id = [], 0, 0
    for entry in entries:
        if _is_ad(entry):
            skipped_ads += 1
            continue
        url = entry.get("titleUrl", "")
        m = _VIDEO_ID_RE.search(url)
        if not m:
            skipped_no_id += 1
            continue
        video_id = m.group(1)

        subtitles = entry.get("subtitles", [])
        channel_name = subtitles[0].get("name") if subtitles else None
        channel_url  = subtitles[0].get("url", "") if subtitles else ""
        cm = _CHANNEL_ID_RE.search(channel_url)
        channel_id = cm.group(1) if cm else None

        rows.append({
            "video_id":     video_id,
            "title":        _strip_watched(entry.get("title", "")),
            "channel_name": channel_name,
            "channel_id":   channel_id,
            "watched_at":   to_utc(entry.get("time", "")),
            "source":       source,
        })
    return rows, skipped_ads, skipped_no_id


# ── Loaders ──────────────────────────────────────────────────────────────────
def load_watches(db, entries: list, source: str) -> tuple[int, int, int]:
    rows, skipped_ads, skipped_no_id = _parse_watch_rows(entries, source)
    before = db.execute("SELECT COUNT(*) FROM watches").fetchone()[0]
    db["watches"].insert_all(rows, ignore=True)
    after  = db.execute("SELECT COUNT(*) FROM watches").fetchone()[0]
    return after - before, skipped_ads, skipped_no_id


def load_yt_searches(db, entries: list) -> int:
    rows = []
    for e in entries:
        title = e.get("title", "")
        if not title.startswith("Searched for "):
            continue
        rows.append({"query": title[len("Searched for "):], "searched_at": to_utc(e.get("time", ""))})
    before = db.execute("SELECT COUNT(*) FROM yt_searches").fetchone()[0]
    db["yt_searches"].insert_all(rows, ignore=True)
    return db.execute("SELECT COUNT(*) FROM yt_searches").fetchone()[0] - before


def load_watch_later(db, csv_content: str) -> int:
    reader = csv.reader(io.StringIO(csv_content))
    next(reader, None)  # skip header
    rows = [
        {"video_id": row[0].strip(), "added_at": to_utc(row[1].strip())}
        for row in reader if len(row) >= 2 and row[0].strip()
    ]
    db["watch_later"].insert_all(rows, replace=True)
    return len(rows)


def load_google_searches(db, entries: list) -> int:
    rows = []
    for e in entries:
        title = e.get("title", "")
        if "Searched for " not in title:
            continue
        query = re.sub(r"^.*?Searched for ", "", title)
        rows.append({"query": query, "searched_at": to_utc(e.get("time", ""))})
    before = db.execute("SELECT COUNT(*) FROM google_searches").fetchone()[0]
    db["google_searches"].insert_all(rows, ignore=True)
    return db.execute("SELECT COUNT(*) FROM google_searches").fetchone()[0] - before


def load_discover(db, entries: list) -> int:
    rows = []
    for e in entries:
        details = e.get("details", [])
        raw_topics = [d["name"] for d in details if "name" in d]
        viewed     = [t[: -len(" - viewed")] for t in raw_topics if t.endswith(" - viewed")]
        all_clean  = [t.replace(" - viewed", "") for t in raw_topics]
        rows.append({
            "snapshot_at":   to_utc(e.get("time", "")),
            "all_topics":    json.dumps(all_clean, ensure_ascii=False),
            "viewed_topics": json.dumps(viewed,    ensure_ascii=False),
        })
    before = db.execute("SELECT COUNT(*) FROM discover_feed").fetchone()[0]
    db["discover_feed"].insert_all(rows, ignore=True)
    return db.execute("SELECT COUNT(*) FROM discover_feed").fetchone()[0] - before


def load_calendar_ics(db, ics_content: str, calendar_name: str) -> int:
    rows = []
    for block in ics_content.split("BEGIN:VEVENT")[1:]:
        end = block.find("END:VEVENT")
        if end == -1:
            continue
        block = block[:end]

        def field(name):
            m = re.search(rf"^{name}[;:][^\n\r]*?:(.+)$|^{name}:(.+)$", block, re.MULTILINE)
            if not m:
                return None
            val = (m.group(1) or m.group(2) or "").strip()
            # unfold RFC 5545 line continuations
            val = re.sub(r"\r?\n[ \t]", "", val)
            return val or None

        start = re.search(r"^DTSTART[^:]*:(.+)$", block, re.MULTILINE)
        if not start:
            continue

        rows.append({
            "calendar_name": calendar_name,
            "summary":       field("SUMMARY"),
            "start_date":    start.group(1).strip(),
            "end_date":      (lambda m: m.group(1).strip() if m else None)(
                                 re.search(r"^DTEND[^:]*:(.+)$", block, re.MULTILINE)),
            "created_at":    field("CREATED"),
        })

    db["calendar_events"].insert_all(rows, ignore=True)
    return len(rows)


_AMOUNT_RE = re.compile(r"[₹$€£]?\s*([\d,]+\.?\d*)")


def load_transactions(db, entries: list) -> int:
    rows = []
    for e in entries:
        title = e.get("title", "")
        if title.startswith(("Sent", "Paid")):
            direction = "sent"
        elif title.startswith("Received"):
            direction = "received"
        else:
            continue
        m = _AMOUNT_RE.search(title)
        if not m:
            continue
        rows.append({
            "amount_inr":    float(m.group(1).replace(",", "")),
            "direction":     direction,
            "transacted_at": to_utc(e.get("time", "")),
        })
    before = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    db["transactions"].insert_all(rows, ignore=True)
    return db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] - before


# ── Spotify loader ───────────────────────────────────────────────────────────
def load_spotify(db, zip_path: Path = ZIP_SPOTIFY) -> tuple[int, int]:
    """Ingest Spotify Extended Streaming History from zip file.

    Reads all Streaming_History_Audio_*.json and Streaming_History_Video_*.json.
    Idempotent: UNIQUE(ts, spotify_track_uri|episode_uri) deduplicates across
    re-runs and across overlapping year files (e.g. Audio_2024 and Audio_2025
    share late-December 2024 records).

    Timestamps normalized to +00:00 suffix (same as watches.watched_at) so all
    cross-table time comparisons work correctly as strings.

    Returns (inserted, already_existed).
    """
    if not zip_path.exists():
        print(f"      [skip] {zip_path.name} not found — place it at project root "
              f"or set SPOTIFY_ZIP env var")
        return 0, 0

    rows = []
    with zipfile.ZipFile(zip_path) as zf:
        history_files = sorted(
            n for n in zf.namelist()
            if ("Streaming_History_Audio_" in n or "Streaming_History_Video_" in n)
            and n.endswith(".json")
        )
        for fname in history_files:
            with zf.open(fname) as f:
                records = json.load(f)
            source = Path(fname).name
            for r in records:
                if r.get("master_metadata_track_name"):
                    content_type = "track"
                elif r.get("episode_name"):
                    content_type = "episode"
                elif r.get("audiobook_title"):
                    content_type = "audiobook"
                else:
                    content_type = "unknown"

                # Normalize platform: first word, lowercase, "web_player" -> "web"
                platform_raw = (r.get("platform") or "").split()[0].lower()
                platform = "web" if platform_raw == "web_player" else platform_raw or None

                rows.append({
                    "ts":                  to_utc(r.get("ts", "")),
                    "ms_played":           int(r.get("ms_played") or 0),
                    "track_name":          r.get("master_metadata_track_name"),
                    "artist_name":         r.get("master_metadata_album_artist_name"),
                    "album_name":          r.get("master_metadata_album_album_name"),
                    "spotify_track_uri":   r.get("spotify_track_uri"),
                    "episode_name":        r.get("episode_name"),
                    "episode_show_name":   r.get("episode_show_name"),
                    "spotify_episode_uri": r.get("spotify_episode_uri"),
                    "reason_start":        r.get("reason_start"),
                    "reason_end":          r.get("reason_end"),
                    "shuffle":             int(bool(r.get("shuffle"))),
                    "skipped":             int(bool(r.get("skipped"))),
                    "offline":             int(bool(r.get("offline"))),
                    "incognito_mode":      int(bool(r.get("incognito_mode"))),
                    "platform":            platform,
                    "conn_country":        r.get("conn_country"),
                    "content_type":        content_type,
                    "source_file":         source,
                })

    before = db.execute("SELECT COUNT(*) FROM spotify_plays").fetchone()[0]
    db["spotify_plays"].insert_all(rows, ignore=True)
    after  = db.execute("SELECT COUNT(*) FROM spotify_plays").fetchone()[0]
    inserted = after - before
    return inserted, len(rows) - inserted


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    db = sqlite_utils.Database(DB_PATH)
    print(f"Echo database: {DB_PATH}\n")

    init_schema(db)
    print("Schema ready.\n")

    # 1. Watches — My Activity YouTube (primary: widest coverage, 2016-2026)
    print("[1/9] Watches: My Activity YouTube")
    with zipfile.ZipFile(ZIP_ACTIVITY) as zf:
        with zf.open("Takeout/My Activity/YouTube/MyActivity.json") as f:
            entries = json.load(f)
    ins, ads, noid = load_watches(db, entries, "my_activity")
    print(f"      +{ins} inserted | {ads} ads dropped | {noid} no video ID")

    # 2. Watches — YouTube Takeout (supplements; UNIQUE constraint deduplicates)
    print("[2/9] Watches: YouTube Takeout")
    with zipfile.ZipFile(ZIP_YT) as zf:
        with zf.open("Takeout/YouTube and YouTube Music/history/watch-history.json") as f:
            entries = json.load(f)
    ins, ads, noid = load_watches(db, entries, "yt_takeout")
    print(f"      +{ins} new unique | {ads} ads dropped | {noid} no video ID")
    total = db.execute("SELECT COUNT(*) FROM watches").fetchone()[0]
    print(f"      Total unique watches: {total:,}\n")

    # 3. YouTube searches
    print("[3/9] YouTube searches")
    with zipfile.ZipFile(ZIP_YT) as zf:
        with zf.open("Takeout/YouTube and YouTube Music/history/search-history.json") as f:
            entries = json.load(f)
    ins = load_yt_searches(db, entries)
    print(f"      +{ins} queries\n")

    # 4. Watch Later
    print("[4/9] Watch Later")
    with zipfile.ZipFile(ZIP_YT) as zf:
        with zf.open("Takeout/YouTube and YouTube Music/playlists/Watch later-videos.csv") as f:
            content = f.read().decode("utf-8", errors="replace")
    ins = load_watch_later(db, content)
    print(f"      +{ins} bookmarks\n")

    # 5. Google searches
    print("[5/9] Google searches")
    with zipfile.ZipFile(ZIP_ACTIVITY) as zf:
        with zf.open("Takeout/My Activity/Search/MyActivity.json") as f:
            entries = json.load(f)
    ins = load_google_searches(db, entries)
    print(f"      +{ins} queries\n")

    # 6. Discover feed
    print("[6/9] Discover feed snapshots")
    with zipfile.ZipFile(ZIP_ACTIVITY) as zf:
        with zf.open("Takeout/My Activity/Discover/MyActivity.json") as f:
            entries = json.load(f)
    ins = load_discover(db, entries)
    print(f"      +{ins} daily snapshots\n")

    # 7. Calendar events
    print("[7/9] Calendar events")
    cal_total = 0
    with zipfile.ZipFile(ZIP_CALENDAR) as zf:
        for path in sorted(n for n in zf.namelist() if n.endswith(".ics")):
            name = Path(path).stem.strip()
            with zf.open(path) as f:
                content = f.read().decode("utf-8", errors="replace")
            ins = load_calendar_ics(db, content, name)
            print(f"      {name}: {ins}")
            cal_total += ins
    print(f"      Total: {cal_total:,} events\n")

    # 8. Google Pay transactions
    print("[8/9] Google Pay transactions")
    with zipfile.ZipFile(ZIP_ACTIVITY) as zf:
        with zf.open("Takeout/My Activity/Google Pay/MyActivity.json") as f:
            entries = json.load(f)
    ins = load_transactions(db, entries)
    print(f"      +{ins} transactions\n")

    # 9. Spotify Extended Streaming History
    print("[9/9] Spotify Extended Streaming History")
    ins, dup = load_spotify(db)
    if ins + dup > 0:
        total_sp = db.execute("SELECT COUNT(*) FROM spotify_plays").fetchone()[0]
        print(f"      +{ins:,} inserted | {dup:,} already existed | {total_sp:,} total\n")
    else:
        print()

    # ── Summary ──────────────────────────────────────────────────────────────
    print("=" * 54)
    print("INGESTION COMPLETE")
    print("=" * 54)
    tables = [
        "watches", "yt_searches", "watch_later", "google_searches",
        "discover_feed", "calendar_events", "transactions",
        "chapters", "chapter_fingerprints", "watch_signals", "reflections",
        "spotify_plays",
    ]
    for t in tables:
        n = db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<22} {n:>6,}")

    print("\nWatch events by year:")
    for year, n in db.execute(
        "SELECT substr(watched_at,1,4) AS y, COUNT(*) FROM watches GROUP BY y ORDER BY y"
    ).fetchall():
        bar = "█" * (n // 100)
        print(f"  {year}  {n:>5,}  {bar}")

    size_kb = DB_PATH.stat().st_size // 1024
    print(f"\nDatabase size: {size_kb:,} KB")
    print(f"Location:      {DB_PATH}")
    print("\nNext: pip install datasette && datasette echo.db")


if __name__ == "__main__":
    main()
