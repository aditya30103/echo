#!/usr/bin/env python3
"""
Echo signals — per-watch engagement scoring.

Computes watch_signals: session membership, rewatch detection,
search-driven detection, autoplay proxy, bookmark status.

Safe to re-run (drops and recomputes from scratch).

Run:
    python signals.py
"""

import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sqlite_utils

BASE    = Path(__file__).parent
DB_PATH = BASE / "echo.db"

SESSION_GAP_MIN  = 30   # gap > 30 min between consecutive watches → new session
                        # standard definition used in YouTube research literature;
                        # tested vs 15/45 min — 30 best matches intuitive session breaks

SEARCH_WIN_MIN   = 10   # a yt_search within 10 min before a watch → is_search_driven=1
                        # intentionally generous: captures "searched, browsed, then watched"
                        # does NOT distinguish which search led to which video

AUTOPLAY_GAP_MIN = 3    # same-channel watch within 3 min of previous → is_autoplay=1
                        # this is a PROXY, not ground truth — YouTube's autoplay
                        # frequently crosses channels; cross-channel autoplay is invisible here


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def compute(db: sqlite_utils.Database) -> list[dict]:
    # ── Load base data ────────────────────────────────────────────────────────
    watches = db.execute("""
        SELECT id, video_id, channel_name, watched_at
        FROM watches ORDER BY watched_at
    """).fetchall()

    search_times = [
        _parse(r[0])
        for r in db.execute(
            "SELECT searched_at FROM yt_searches ORDER BY searched_at"
        ).fetchall()
    ]

    bookmarked = {
        r[0] for r in db.execute("SELECT video_id FROM watch_later").fetchall()
    }

    # Total watches per video_id (for rewatch_count)
    video_total: dict[str, int] = defaultdict(int)
    for _, vid, _, _ in watches:
        video_total[vid] += 1

    # ── Session assignment ────────────────────────────────────────────────────
    # Group consecutive watches with gap ≤ SESSION_GAP_MIN into sessions.
    sessions: list[list[tuple]] = []
    current: list[tuple] = []

    for watch_id, vid, channel, ts in watches:
        dt = _parse(ts)
        if not current or (dt - current[-1][3]).total_seconds() / 60 > SESSION_GAP_MIN:
            if current:
                sessions.append(current)
            current = [(watch_id, vid, channel, dt)]
        else:
            current.append((watch_id, vid, channel, dt))
    if current:
        sessions.append(current)

    # ── Signal computation ────────────────────────────────────────────────────
    rows: list[dict] = []
    seen_videos: set[str] = set()
    search_ptr: int = 0
    session_id: int = 0

    for session in sessions:
        session_id += 1
        session_len = len(session)

        for depth_0, (watch_id, vid, channel, dt) in enumerate(session):
            depth = depth_0 + 1

            # is_rewatch: video seen in an earlier watch
            is_rewatch = 1 if vid in seen_videos else 0
            seen_videos.add(vid)

            # was_bookmarked: video was in watch_later at any point
            was_bookmarked = 1 if vid in bookmarked else 0

            # is_search_driven: any yt_search within SEARCH_WIN_MIN before this watch
            win_start = dt - timedelta(minutes=SEARCH_WIN_MIN)
            # advance pointer past searches before the window
            while search_ptr < len(search_times) and search_times[search_ptr] < win_start:
                search_ptr += 1
            is_search_driven = 0
            tmp = search_ptr
            while tmp < len(search_times) and search_times[tmp] <= dt:
                is_search_driven = 1
                break

            # is_autoplay: same channel as previous watch in session, gap < AUTOPLAY_GAP_MIN
            is_autoplay = 0
            if depth > 1:
                _, _, prev_channel, prev_dt = session[depth_0 - 1]
                gap_min = (dt - prev_dt).total_seconds() / 60
                if channel and prev_channel and channel == prev_channel and gap_min < AUTOPLAY_GAP_MIN:
                    is_autoplay = 1

            rows.append({
                "watch_id":         watch_id,
                "session_id":       session_id,
                "session_depth":    depth,
                "session_length":   session_len,
                "is_rewatch":       is_rewatch,
                "rewatch_count":    video_total[vid],
                "is_search_driven": is_search_driven,
                "is_autoplay":      is_autoplay,
                "was_bookmarked":   was_bookmarked,
            })

    return rows, session_id


def print_summary(rows: list[dict], n_sessions: int):
    total     = len(rows)
    rewatches = sum(1 for r in rows if r["is_rewatch"])
    search_d  = sum(1 for r in rows if r["is_search_driven"])
    autoplay  = sum(1 for r in rows if r["is_autoplay"])
    bookmarks = sum(1 for r in rows if r["was_bookmarked"])
    solo      = sum(1 for r in rows if r["session_length"] == 1)

    deep_sessions = defaultdict(int)
    for r in rows:
        deep_sessions[r["session_id"]] = max(
            deep_sessions[r["session_id"]], r["session_depth"]
        )
    long_sessions = sum(1 for d in deep_sessions.values() if d >= 5)

    print("=" * 52)
    print("WATCH SIGNALS COMPLETE")
    print("=" * 52)
    print(f"  Total watches:      {total:,}")
    print(f"  Sessions:           {n_sessions:,}")
    print(f"  Solo sessions:      {solo:,}  ({solo * 100 // total}% of watches)")
    print(f"  Long sessions (5+): {long_sessions:,}")
    print(f"  Rewatches:          {rewatches:,}  ({rewatches * 100 // total}%)")
    print(f"  Search-driven:      {search_d:,}  ({search_d * 100 // total}%)")
    print(f"  Autoplay proxy:     {autoplay:,}  ({autoplay * 100 // total}%)")
    print(f"  Bookmarked videos:  {bookmarks:,}  ({bookmarks * 100 // total}%)")

    print()
    print("Most rewatched videos:")
    from collections import Counter
    rewatch_vids = [r["watch_id"] for r in rows if r["is_rewatch"]]
    # need titles — query separately
    return total, n_sessions


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    db = sqlite_utils.Database(DB_PATH)

    print("Computing watch signals...", flush=True)
    rows, n_sessions = compute(db)
    print(f"  {len(rows):,} watches across {n_sessions:,} sessions", flush=True)

    print("Writing watch_signals table...", flush=True)
    db.execute("DROP TABLE IF EXISTS watch_signals")
    db["watch_signals"].insert_all(rows, pk="watch_id")
    db.conn.commit()

    print()
    print_summary(rows, n_sessions)

    # Top rewatched videos
    print("Most rewatched videos (top 10):")
    top_rewatched = db.execute("""
        SELECT w.title, COUNT(*) AS n
        FROM watches w
        JOIN watch_signals ws ON w.id = ws.watch_id
        WHERE ws.is_rewatch = 1
        GROUP BY w.video_id
        ORDER BY n DESC LIMIT 10
    """).fetchall()
    for title, n in top_rewatched:
        print(f"  {n+1:>2}x  {title[:70]}")

    print()
    print("Top search-driven watches (most searches just before watching):")
    top_search = db.execute("""
        SELECT w.title, COUNT(*) AS n
        FROM watches w
        JOIN watch_signals ws ON w.id = ws.watch_id
        WHERE ws.is_search_driven = 1
        GROUP BY w.video_id
        ORDER BY n DESC LIMIT 5
    """).fetchall()
    for title, n in top_search:
        print(f"  {n:>2}x  {title[:70]}")


if __name__ == "__main__":
    main()
