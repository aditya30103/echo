"""youtube_lookup tool — YouTube Data API videos.list wrapper."""

import json
import os
from datetime import date

# Module-level quota tracker: (date, units_used). Resets when date changes.
# Quota resets at midnight UTC; we track against UTC date to match the API's reset.
_quota_state: tuple[date, int] = (date(2000, 1, 1), 0)
_QUOTA_DAILY_LIMIT = 9000  # conservative — full API limit is 10,000 units/day
_UNITS_PER_CALL    = 1     # videos.list costs 1 unit


def _load_env() -> None:
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from embed_common import load_env
    load_env()


def run_youtube_lookup(video_id: str) -> str:
    """Return metadata for a YouTube video via Data API.

    Quota-aware: refuses calls past 9,000 units on the current UTC calendar day.
    Returns [EXTERNAL] tagged JSON or an [EXTERNAL] ERROR string.
    """
    global _quota_state

    _load_env()
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        return "[EXTERNAL] ERROR: YOUTUBE_API_KEY not configured in .env."

    today = date.today()
    used_date, used_units = _quota_state
    if used_date != today:
        _quota_state = (today, 0)
        used_units = 0

    if used_units + _UNITS_PER_CALL > _QUOTA_DAILY_LIMIT:
        return (
            f"[EXTERNAL] ERROR: YouTube API daily quota exceeded "
            f"({used_units}/{_QUOTA_DAILY_LIMIT} units used today). "
            "Quota resets at midnight UTC."
        )

    try:
        from googleapiclient.discovery import build

        youtube = build("youtube", "v3", developerKey=api_key)
        resp = youtube.videos().list(
            part="snippet,contentDetails,statistics",
            id=video_id,
        ).execute()

        _quota_state = (today, used_units + _UNITS_PER_CALL)

        items = resp.get("items", [])
        if not items:
            return f"[EXTERNAL] No video found for id={video_id!r}."

        item    = items[0]
        snippet = item.get("snippet", {})
        details = item.get("contentDetails", {})
        stats   = item.get("statistics", {})

        result = {
            "video_id":     video_id,
            "title":        snippet.get("title"),
            "channel":      snippet.get("channelTitle"),
            "published_at": (snippet.get("publishedAt") or "")[:10],
            "description":  (snippet.get("description") or "")[:300],
            "tags":         (snippet.get("tags") or [])[:10],
            "duration_iso": details.get("duration"),
            "view_count":   stats.get("viewCount"),
            "like_count":   stats.get("likeCount"),
        }
        return f"[EXTERNAL]\n{json.dumps(result, indent=2)}"

    except ImportError as e:
        return f"[EXTERNAL] ERROR: Missing dependency — {e}. Run: pip install google-api-python-client"
    except Exception as e:
        return f"[EXTERNAL] ERROR: {e}"
