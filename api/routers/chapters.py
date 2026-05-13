"""Chapter and reflection data."""

import json
from fastapi import APIRouter, Depends
from api.db import get_db
import sqlite_utils

router = APIRouter(prefix="/api/chapters", tags=["chapters"])


@router.get("")
def list_chapters(db: sqlite_utils.Database = Depends(get_db)):
    rows = db.execute("""
        SELECT
            c.id, c.start_at, c.end_at, c.label,
            r.reflection,
            cf.night_ratio, cf.modal_hour, cf.channel_density_score,
            cf.long_form_ratio, cf.shorts_ratio, cf.median_duration_seconds,
            cf.top_categories
        FROM chapters c
        LEFT JOIN reflections r        ON r.chapter_id = c.id AND r.kind = 'chapter'
        LEFT JOIN chapter_fingerprints cf ON cf.chapter_id = c.id
        ORDER BY c.start_at
    """).fetchall()

    keys = [
        "id", "start_at", "end_at", "label", "reflection",
        "night_ratio", "modal_hour", "channel_density_score",
        "long_form_ratio", "shorts_ratio", "median_duration_seconds",
        "top_categories_raw",
    ]
    out = []
    for row in rows:
        d = dict(zip(keys, row))
        raw = d.pop("top_categories_raw")
        try:
            d["top_categories"] = json.loads(raw) if raw else []
        except (TypeError, ValueError):
            d["top_categories"] = []
        out.append(d)

    return {"chapters": out, "total": len(out)}
