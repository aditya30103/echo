"""Binge sessions and agency map endpoints."""

from fastapi import APIRouter, Depends, Query
import sqlite_utils

from api.constants import IST_OFFSET
from api.db import get_db

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("/sessions")
def top_sessions(
    limit: int = Query(50, le=200),
    min_depth: int = Query(5, ge=2),
    db: sqlite_utils.Database = Depends(get_db),
):
    rows = db.execute(f"""
        SELECT
            ws.session_id,
            MAX(ws.session_length)                              AS depth,
            MIN(datetime(w.watched_at, '{IST_OFFSET}'))         AS session_start,
            MAX(datetime(w.watched_at, '{IST_OFFSET}'))         AS session_end,
            CAST(
                (julianday(MAX(datetime(w.watched_at, '{IST_OFFSET}')))
                 - julianday(MIN(datetime(w.watched_at, '{IST_OFFSET}'))))
                * 24 * 60
            AS INTEGER)                                         AS duration_min,
            COUNT(*)                                            AS watch_count,
            (
                SELECT COALESCE(vm2.channel_title, '')
                FROM watches w2
                LEFT JOIN video_metadata vm2 ON w2.video_id = vm2.video_id
                LEFT JOIN watch_signals ws2  ON ws2.watch_id = w2.id
                WHERE ws2.session_id = ws.session_id
                  AND vm2.channel_title IS NOT NULL
                GROUP BY vm2.channel_title
                ORDER BY COUNT(*) DESC
                LIMIT 1
            )                                                   AS top_channel,
            SUM(ws.is_search_driven)                            AS searched_count,
            SUM(ws.is_autoplay)                                 AS autoplay_count,
            CAST(strftime('%H', MIN(datetime(w.watched_at, '{IST_OFFSET}'))) AS INTEGER)
                                                                AS start_hour
        FROM watch_signals ws
        JOIN watches w ON ws.watch_id = w.id
        WHERE ws.session_length >= ?
        GROUP BY ws.session_id
        ORDER BY MAX(ws.session_length) DESC
        LIMIT ?
    """, [min_depth, limit]).fetchall()

    keys = [
        "session_id", "depth", "session_start", "session_end",
        "duration_min", "watch_count", "top_channel",
        "searched_count", "autoplay_count", "start_hour",
    ]
    sessions = []
    for row in rows:
        s = dict(zip(keys, row))
        h = s["start_hour"]
        s["is_night"] = h is not None and (h >= 23 or h < 4)
        sessions.append(s)

    return {"sessions": sessions}


@router.get("/agency")
def agency_by_chapter(db: sqlite_utils.Database = Depends(get_db)):
    rows = db.execute(f"""
        SELECT
            c.id        AS chapter_id,
            c.label,
            c.start_at,
            c.end_at,
            COUNT(*)                    AS total,
            SUM(ws.is_search_driven)    AS searched,
            SUM(ws.was_bookmarked)      AS bookmarked,
            SUM(ws.is_autoplay)         AS autoplay,
            SUM(ws.is_rewatch)          AS rewatch
        FROM watch_signals ws
        JOIN watches w ON ws.watch_id = w.id
        JOIN chapters c
          ON datetime(w.watched_at, '{IST_OFFSET}') BETWEEN c.start_at AND c.end_at
        GROUP BY c.id
        ORDER BY c.start_at
    """).fetchall()

    keys = ["chapter_id", "label", "start_at", "end_at", "total",
            "searched", "bookmarked", "autoplay", "rewatch"]
    chapters = []
    for row in rows:
        d = dict(zip(keys, row))
        t = d["total"] or 1
        d["searched_pct"]   = round(d["searched"]   / t * 100, 1)
        d["bookmarked_pct"] = round(d["bookmarked"]  / t * 100, 1)
        d["autoplay_pct"]   = round(d["autoplay"]    / t * 100, 1)
        d["rewatch_pct"]    = round(d["rewatch"]     / t * 100, 1)
        chapters.append(d)

    return {"chapters": chapters}
