# Echo — Data Dictionary

What each table and column means, how it was computed, and known limitations.
For how to run the pipeline, see RUNBOOK.md.

---

## Source tables (populated by ingest.py)

### `watches`

One row per unique YouTube video watch event.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-assigned |
| video_id | TEXT | YouTube video ID (11-char, e.g. `dQw4w9WgXcQ`) |
| title | TEXT | Video title at time of watch (may differ from current title) |
| channel_name | TEXT | Display name of channel (nullable — missing from some Takeout entries) |
| channel_id | TEXT | YouTube channel ID (nullable) |
| watched_at | TEXT | UTC ISO-8601 timestamp |
| source | TEXT | `my_activity` or `yt_takeout` (two overlapping Takeout sources, deduped by UNIQUE(video_id, watched_at)) |

**Coverage:** 2020–2026. 2017–2019 is entirely missing (YouTube History was paused or auto-deleted).
**Dedup:** Two Takeout sources were merged; duplicates removed by UNIQUE(video_id, watched_at).
**Note:** `title` reflects the title at export time. Deleted/private videos retain their last-known title.

---

### `video_metadata`

Enriched metadata fetched from YouTube Data API v3.

| Column | Type | Notes |
|--------|------|-------|
| video_id | TEXT PK | |
| title | TEXT | Current title from API (may differ from watches.title for edited videos) |
| channel_id | TEXT | |
| channel_title | TEXT | |
| category_id | INTEGER | YouTube category ID |
| category_name | TEXT | Human-readable: "Education", "News & Politics", etc. |
| duration_seconds | INTEGER | Video duration. 0 for livestreams. Used for short/long classification. |
| tags | TEXT | JSON array of video tags |
| published_at | TEXT | Video publish date |
| fetched_at | TEXT | When enrich.py fetched this row |
| available | INTEGER | 1 = available, 0 = deleted or private |

**Coverage:** ~5,568 available (out of 6,280 unique videos). ~222 are deleted/private (available=0).
**Shorts detection:** `duration_seconds > 0 AND duration_seconds <= 60` → YouTube Short.
**Long-form:** `duration_seconds > 1200` (>20 min).

---

### `yt_searches`

YouTube search queries extracted from My Activity Takeout.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| query | TEXT | Raw search string |
| searched_at | TEXT | UTC ISO-8601 timestamp |

**Coverage:** All available searches. Used in signals.py to compute `is_search_driven`.

---

### `watch_later`

Videos that were added to Watch Later playlist.

| Column | Type | Notes |
|--------|------|-------|
| video_id | TEXT PK | |
| added_at | TEXT | UTC ISO-8601 timestamp |

**Note:** This is a snapshot from Takeout export date. Videos removed from Watch Later before export are not present. Used in signals.py for `was_bookmarked`.

---

### `calendar_events`

Personal calendar events from Google Calendar ICS export.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| calendar_name | TEXT | Calendar name (e.g., email address, "Semester 8") |
| summary | TEXT | Event title (nullable — some ICS events have no SUMMARY) |
| start_date | TEXT | Raw ICS format: `YYYYMMDD` or `YYYYMMDDTHHMMSSZ` — NOT ISO-8601 |
| end_date | TEXT | Same format as start_date |
| created_at | TEXT | ICS CREATED field |

**Coverage:** Mostly 2022–2026. Sparse before 2022 (only 9 events pre-2022).
**Important:** `start_date` is stored as raw ICS format. To compare against ISO dates, use:
`substr(start_date,1,4)||'-'||substr(start_date,5,2)||'-'||substr(start_date,7,2)`
This is already handled correctly in reflect.py. Don't use `start_date BETWEEN` directly.

---

### `google_searches`, `discover_feed`, `transactions`

Supporting context tables. See schema in ingest.py for column details.
- `google_searches` — Google Search queries, 2024–2026 only (1-year Chrome retention)
- `discover_feed` — Daily Google Discover topic snapshots, 2020–2026
- `transactions` — Google Pay sent/received amounts, depends on your data

---

## Derived tables (populated by later pipeline stages)

### `chapters` (detect.py)

One row per behavioral chapter detected by PELT changepoint analysis.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| start_at | TEXT | ISO date of chapter start (Monday) |
| end_at | TEXT | ISO date of chapter end (Sunday of final week) |
| label | TEXT | Auto-generated: "Chapter 1", "Chapter 2", … |

**How chapters are computed:** Weekly signal (8 dimensions, see below) is z-score normalised and fed to PELT with RBF cost. Breakpoints are converted to chapter boundaries. Current config: penalty=2 → 16 chapters.
**Recompute:** `python detect.py` drops and rewrites this table. Use `--dry-run` to preview before committing.

---

### `chapter_fingerprints` (detect.py)

Summary statistics for each chapter's watch behavior.

| Column | Type | Notes |
|--------|------|-------|
| chapter_id | INTEGER PK FK→chapters | |
| top_categories | TEXT | JSON object: `{"Education": 45.2, "News & Politics": 18.1, …}` — top 5 categories by % |
| median_duration_seconds | REAL | Median video length in seconds for this chapter |
| modal_hour | INTEGER | Most common hour of day (IST, 0–23) for watches in this chapter |
| channel_density_score | REAL | unique_channels / total_watches. Higher = more varied. 1.0 = every video from different channel. |
| night_ratio | REAL | Fraction of watches between 22:00–04:00 IST |
| shorts_ratio | REAL | Fraction of watches that are YouTube Shorts (duration ≤ 60s) |
| long_form_ratio | REAL | Fraction of watches that are long-form (duration > 1200s = 20 min) |

---

### `watch_signals` (signals.py)

Per-watch engagement signals. One row per row in `watches`.

| Column | Type | Notes |
|--------|------|-------|
| watch_id | INTEGER PK FK→watches | |
| session_id | INTEGER | Sequential session number (1-indexed, chronological) |
| session_depth | INTEGER | Position within session (1 = first video, 2 = second, …) |
| session_length | INTEGER | Total videos in this session |
| is_rewatch | INTEGER | 1 if this video_id was watched in any earlier session or earlier in this session |
| rewatch_count | INTEGER | Total number of times this video_id appears in all of watches |
| is_search_driven | INTEGER | 1 if any yt_search exists within 10 min before this watch |
| is_autoplay | INTEGER | 1 if same channel as previous watch AND gap < 3 min (proxy — see limitation) |
| was_bookmarked | INTEGER | 1 if this video_id appears in watch_later at any point |

**Session definition:** Consecutive watches with gap ≤ 30 min belong to the same session.
**is_search_driven limitation:** Does not identify *which* search led to the watch — only that a search happened within the window. A search for "pasta recipes" followed by watching a tech video would still set this to 1.
**is_autoplay limitation:** Only detects same-channel autoplay. YouTube frequently autoplays cross-channel; this is invisible here. True autoplay rate is higher than `is_autoplay` suggests.
**was_bookmarked:** Reflects snapshot at Takeout export date, not whether the video was bookmarked at watch time.

---

### `reflections` (reflect.py)

GPT-4o generated narrative reflections.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| chapter_id | INTEGER FK→chapters | NULL for kind='autobiography' |
| kind | TEXT | `chapter` — per-chapter reflection; `autobiography` — full arc narrative |
| prompt_text | TEXT | Full prompt sent to GPT-4o (stored for reproducibility and prompt iteration) |
| reflection | TEXT | GPT-4o response |
| model | TEXT | Model used (e.g., `gpt-4o`) |
| created_at | TEXT | UTC timestamp |

**Note:** Rows are appended on each run — re-running adds new rows, doesn't overwrite. Compare runs by `created_at` to see how reflections evolve with new data.

---

## The 8-dimensional weekly signal (detect.py)

The signal used for PELT changepoint detection. One vector per week.

| Dimension | Description |
|-----------|-------------|
| night_ratio | Fraction of watches between 22:00–04:00 IST |
| shorts_ratio | Fraction of watches that are YouTube Shorts (≤60s) |
| long_form_ratio | Fraction of watches that are long-form (>1200s) |
| education | Fraction of watches in "Education" category |
| news | Fraction of watches in "News & Politics" category |
| science | Fraction of watches in "Science & Technology" category |
| sports | Fraction of watches in "Sports" category |
| people | Fraction of watches in "People & Blogs" category |

Sparse weeks (< 3 watches) are linearly interpolated from neighbours before PELT runs.
Signal is z-score normalised per-dimension before PELT.

---

## Key data facts

- **Total watches:** 6,280 (2020–2026)
- **2017–2019:** Entirely missing
- **Sparse era:** 2020–2023 (~854 watches across 4 years)
- **Dense era:** 2024–2026 (~5,426 watches)
- **Night signal:** 26% of watches are 22:00–04:00 IST
- **Shorts:** First appeared meaningfully in Ch15 (Nov 2024), ~19–20% since then
- **Top categories:** Education 18.7%, News & Politics 18.4%, People & Blogs 16.4%
- **Median video duration:** 5m 44s
- **Sessions:** 1,928 total; 865 solo (1 video), 420 long (5+ videos)
- **Most rewatched:** Anuv Jain - INAAM (11x)
