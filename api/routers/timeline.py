"""Archaeology timeline queries — IST-aware."""

from fastapi import APIRouter, Depends, Query
from api.db import get_db
import sqlite_utils

router = APIRouter(prefix="/api/timeline", tags=["timeline"])

IST_OFFSET = "+330 minutes"  # UTC+5:30; all behavioral hour calcs use this

NIGHT_WHERE = """
    strftime('%H', datetime(w.watched_at, '{o}')) >= '23'
    OR strftime('%H', datetime(w.watched_at, '{o}')) < '04'
""".format(o=IST_OFFSET)

TIMELINE_SELECT = """
    SELECT
        w.id                                                          AS watch_id,
        w.video_id,
        datetime(w.watched_at, '{o}')                                 AS watched_at_ist,
        COALESCE(vm.title, w.title, w.video_id)                       AS title,
        COALESCE(vm.channel_title, '')                                AS channel,
        ws.is_rewatch,
        ws.session_depth,
        ws.is_search_driven,
        c.id                                                          AS chapter_id,
        c.label                                                       AS chapter_label,
        c.start_at,
        c.end_at
    FROM watches w
    LEFT JOIN video_metadata vm  ON w.video_id = vm.video_id
    LEFT JOIN watch_signals  ws  ON ws.watch_id = w.id
    LEFT JOIN chapters       c   ON datetime(w.watched_at, '{o}')
                                        BETWEEN c.start_at AND c.end_at
""".format(o=IST_OFFSET)


def _row_to_dict(row) -> dict:
    keys = [
        "watch_id", "video_id", "watched_at_ist", "title", "channel",
        "is_rewatch", "session_depth", "is_search_driven",
        "chapter_id", "chapter_label", "start_at", "end_at",
    ]
    d = dict(zip(keys, row))
    d["thumbnail_url"] = f"https://i.ytimg.com/vi/{d['video_id']}/default.jpg"
    return d


@router.get("/night")
def night_timeline(db: sqlite_utils.Database = Depends(get_db)):
    """All 11 PM – 4 AM IST watches across all time, ordered chronologically."""
    sql = f"{TIMELINE_SELECT} WHERE {NIGHT_WHERE} ORDER BY w.watched_at"
    rows = db.execute(sql).fetchall()
    return {"items": [_row_to_dict(r) for r in rows], "total": len(rows)}


@router.get("")
def month_timeline(
    month: str = Query(..., description="YYYY-MM", pattern=r"^\d{4}-\d{2}$"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: sqlite_utils.Database = Depends(get_db),
):
    """Enriched watches for a given month, paginated."""
    year, mo = month.split("-")
    # match IST month: watches from the last few UTC hours of the previous month
    # can fall into the current IST month, so filter on the IST-adjusted timestamp
    where = f"""
        strftime('%Y-%m', datetime(w.watched_at, '{IST_OFFSET}')) = '{month}'
    """
    count_sql = f"""
        SELECT COUNT(*) FROM watches w
        WHERE {where}
    """
    total = db.execute(count_sql).fetchone()[0]

    sql = f"""
        {TIMELINE_SELECT}
        WHERE {where}
        ORDER BY w.watched_at
        LIMIT {limit} OFFSET {offset}
    """
    rows = db.execute(sql).fetchall()
    return {
        "items": [_row_to_dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
