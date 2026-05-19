# Echo — Data Dictionary

What each table and column means, how it was computed, and known limitations.
For how to run the pipeline, see [RUNBOOK.md](./RUNBOOK.md).

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

### `google_searches`

Google Search queries extracted from My Activity Takeout.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| query | TEXT | Raw search string |
| searched_at | TEXT | UTC ISO-8601 timestamp |

**Coverage:** 2024–2026 only. Chrome retains 1 year of search history in Takeout exports; older searches are not present.
**Dedup:** UNIQUE(query, searched_at) — same query at the same timestamp is deduplicated.
**Row count:** ~4,038 entries; ~3,211 unique queries (used in the lancedb `google_searches` table).
**Note:** Distinct from `yt_searches` — these are Google web searches, not YouTube searches.

---

### `discover_feed`

Daily Google Discover topic snapshots from My Activity Takeout.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| snapshot_at | TEXT | UTC ISO-8601 timestamp |
| all_topics | TEXT | JSON array of all topics shown in that snapshot |
| viewed_topics | TEXT | JSON array of topics the user clicked on |

**Coverage:** 2020–2026, 521 snapshots.

---

### `transactions`

Google Pay sent/received amounts from My Activity Takeout.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| amount_inr | REAL | Amount in INR |
| direction | TEXT | `'sent'` or `'received'` |
| transacted_at | TEXT | UTC ISO-8601 timestamp |

**Coverage:** depends on the dates Google Pay was your primary payment app
(activity is only exported as long as it was being recorded).

---

### `spotify_plays`

One row per Spotify streaming event from Extended Streaming History.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-assigned |
| ts | TEXT | UTC ISO-8601 timestamp (`+00:00` suffix — normalised from Spotify's `Z` on ingest) |
| ms_played | INTEGER | Milliseconds played. 0 = skipped before any audio. Not normalized by track duration — use with `spotify_tracks.duration_ms` for completion ratio. |
| track_name | TEXT | Track title (NULL for episodes/audiobooks) |
| artist_name | TEXT | Album artist name (NULL for episodes/audiobooks) |
| album_name | TEXT | Album name (NULL for episodes/audiobooks) |
| spotify_track_uri | TEXT | Spotify URI, e.g. `spotify:track:...` (NULL for non-tracks) |
| episode_name | TEXT | Podcast episode title (NULL for tracks/audiobooks) |
| episode_show_name | TEXT | Podcast show name (NULL for tracks/audiobooks) |
| spotify_episode_uri | TEXT | Spotify URI for the episode (NULL for non-episodes) |
| reason_start | TEXT | Why playback started: `trackdone` (prev finished), `clickrow`/`playbtn` (manual), `fwdbtn`/`backbtn` (skip), `appload`/`remote` (app launch or remote control) |
| reason_end | TEXT | Why playback ended: `trackdone` (finished), `fwdbtn`/`backbtn` (skipped), `logout`, `endplay`, `remote` |
| shuffle | INTEGER | 1 = shuffle was active when this play started |
| skipped | INTEGER | 1 = Spotify internally marked this play as skipped (< ~50% played, forward-skipped) |
| offline | INTEGER | 1 = played from offline cache |
| incognito_mode | INTEGER | 1 = private session (not counted in Spotify stats) |
| platform | TEXT | Normalised platform: `android`, `ios`, `windows`, `macos`, `web`, `chromecast`, `speaker`, etc. First word of raw platform string, lowercased; `web_player` → `web`. |
| conn_country | TEXT | 2-letter ISO country code where the play occurred (e.g. `IN`) |
| content_type | TEXT | `track` / `episode` / `audiobook` / `unknown` — detected from which metadata fields are non-null |
| source_file | TEXT | Which JSON file this row came from (e.g. `Streaming_History_Audio_2025.json`) |

**Coverage:** All available Extended Streaming History. 16,678 plays across all history files.
**Dedup:** `UNIQUE(ts, COALESCE(spotify_track_uri, spotify_episode_uri, ''))` — safe to re-run and handles overlap between year files (Audio_2024 and Audio_2025 share late December 2024).
**Timestamp:** Normalised from Spotify's `Z` suffix to `+00:00` on ingest. Cross-table string comparison with `watches.watched_at` and other tables is safe. SQLite `strftime()`/`datetime()` handle both formats identically — the normalisation is for string-sort safety only.
**IST hour:** `strftime('%H', datetime(ts, '+330 minutes'))` — same pattern as all other tables.
**Skip detection:** `skipped=1` is Spotify's own flag (forward-skip, incomplete play). `reason_end='fwdbtn'` is a superset that also includes backward-skip. Both are independent of `ms_played`.
**Repeat detection:** Same `(ts, spotify_track_uri)` pair cannot recur (UNIQUE constraint). Repeated listens to the same track appear as distinct rows with different `ts`.
**Duration data absent:** `ms_played` is raw play time, but track duration (`duration_ms`) is not in the streaming export. Completion ratio requires joining `spotify_tracks` (populated by the optional `enrich_spotify.py` step).
**Cross-modal JOIN:** To align Spotify plays with YouTube watches by IST week: `strftime('%Y-%W', datetime(ts, '+330 minutes'))` on `spotify_plays` equals `strftime('%Y-%W', datetime(watched_at, '+330 minutes'))` on `watches`.

---

### `spotify_tracks`

One row per unique `spotify_track_uri` — enriched metadata from the Spotify Web API.
Populated by `enrich_spotify.py` (optional step, requires Spotify Developer app credentials).

| Column | Type | Notes |
|--------|------|-------|
| spotify_track_uri | TEXT PK | Same URI as in `spotify_plays.spotify_track_uri` |
| track_name | TEXT | Track title from Spotify API |
| artist_name | TEXT | Primary artist display name |
| artist_uri | TEXT | Spotify URI for the primary artist (used internally to fetch genres) |
| album_name | TEXT | Album name |
| duration_ms | INTEGER | Track duration in milliseconds — **required for Phase 3 completion_ratio** |
| popularity | INTEGER | 0–100 Spotify popularity score (based on recent stream counts globally) |
| explicit | INTEGER | 1 = explicit content flag set by Spotify |
| genres | TEXT | JSON array of genres from the primary artist, e.g. `["bollywood", "pop"]` |
| valence | REAL | 0–1 musical positiveness (NULL if app registered after Nov 2024) |
| energy | REAL | 0–1 perceptual intensity (NULL if app registered after Nov 2024) |
| danceability | REAL | 0–1 danceability score (NULL if app registered after Nov 2024) |
| tempo | REAL | Estimated BPM (NULL if app registered after Nov 2024) |
| acousticness | REAL | 0–1 acoustic confidence (NULL if app registered after Nov 2024) |
| instrumentalness | REAL | 0–1 vocal absence prediction (NULL if app registered after Nov 2024) |
| loudness | REAL | Average loudness in dB, typically –60 to 0 (NULL if app registered after Nov 2024) |
| speechiness | REAL | 0–1 spoken word presence (NULL if app registered after Nov 2024) |
| mode | INTEGER | 1 = major key, 0 = minor key (NULL if app registered after Nov 2024) |
| musical_key | INTEGER | Pitch class 0–11 (C=0, C#=1, …, B=11). Named `musical_key` to avoid SQLite reserved word `key`. (NULL if app registered after Nov 2024) |
| audio_features_available | INTEGER | 1 = audio features were fetched; 0 = 403 returned (deprecated for this app) |
| fetched_at | TEXT | UTC timestamp of Spotify enrichment |
| artist_lastfm_tags | TEXT | JSON array of Last.fm artist-level top tags, e.g. `["bollywood","Hindi","Indian"]`. Populated by `enrich_music_meta.py` Tier 1. NULL means Tier 1 failed for this artist (still meta_enriched_at is set so we don't retry). |
| lastfm_tags | TEXT | JSON array of Last.fm track-level top tags. Populated by `enrich_music_meta.py` Tier 2 for the top-N most-played tracks only. NULL means Tier 2 hasn't run for this track. `"[]"` means Tier 2 ran but found nothing (or pylast.WSError'd). |
| meta_enriched_at | TEXT | UTC ISO timestamp when this row was last touched by `enrich_music_meta.py`. NULL = never touched. Distinct from `fetched_at` (Spotify enrichment timestamp). |

**Join to plays:** `spotify_tracks.spotify_track_uri = spotify_plays.spotify_track_uri`
**Completion ratio:** `CAST(spotify_plays.ms_played AS REAL) / spotify_tracks.duration_ms` (clamp to 1.0 max — some plays slightly exceed duration due to buffering)
**Genre analysis:** `json_each(genres)` to unnest the array in SQLite: `SELECT value FROM json_each(genres)`
**Audio features:** NULL for apps registered after November 2024. `audio_features_available=0` marks these rows.
**Last.fm tags vs Spotify genres:** Spotify's `genres` column is curated taxonomy from the artist record; `artist_lastfm_tags` is community-tagged vocabulary (broader: genre + mood + locale + era). For mood queries prefer the Last.fm columns; for clean genre filters prefer `genres`. Columns are kept in schema for forward compatibility.

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

### `spotify_signals` (signals.py)

Per-play behavioral signals for Spotify. One row per row in `spotify_plays`. Populated by `signals.py` alongside `watch_signals`. 16,678 rows across 2,165 sessions.

| Column | Type | Notes |
|--------|------|-------|
| play_id | INTEGER PK FK→spotify_plays | |
| session_id | INTEGER | Sequential Spotify session number (1-indexed, chronological) |
| session_depth | INTEGER | Position within session (1 = first play) |
| session_length | INTEGER | Total plays in this session |
| is_repeat | INTEGER | 1 if this `spotify_track_uri` was played at any earlier point in history |
| prior_play_count | INTEGER | Number of times this URI was played before this instance (0 = first listen) |
| fully_played | INTEGER | 1 if `reason_end = 'trackdone'` (track finished naturally — authoritative completion signal) |
| user_skipped | INTEGER | 1 if `reason_end = 'fwdbtn'` OR `skipped = 1` (user actively cut the track short) |
| intent_class | TEXT | Derived from `reason_start`: `intentional` (clickrow/playbtn), `passive` (trackdone), `seek` (fwdbtn/backbtn), `session_start` (appload/remote/trackerror), `unknown` |

**Session definition:** Consecutive plays with gap ≤ 30 min → same session (identical logic to `watch_signals`). Sessions are comparable across both tables.
**fully_played:** Prefer this over computing `ms_played / duration_ms` — `trackdone` is set by Spotify's playback engine when the track actually ends, independent of timing.
**user_skipped:** `reason_end = 'fwdbtn'` and `skipped = 1` are independent signals; either alone is sufficient. `user_skipped = 1` means the user did not want to continue listening.
**prior_play_count:** 0 means first ever listen. Use `is_repeat` for binary repeat detection, `prior_play_count` for affinity depth (e.g., tracks with prior_play_count ≥ 10 are obsessions).
**intent_class cross-modal:** `passive` in Spotify (algorithm played next) maps conceptually to `is_autoplay` in YouTube, but Spotify's signal is authoritative (direct from playback engine) rather than a proxy.

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

## lancedb vector index (populated by embed.py)

Stored in `./lancedb/` (not committed — gitignored, regenerable from echo.db).
Model: `text-embedding-3-small`, 1536 dimensions. Each table has a `vector` column plus the source columns below.

### `reflections` (lancedb)

| Column | Type | Notes |
|--------|------|-------|
| chapter_id | int | FK → chapters.id |
| start_at | str | Chapter start ISO date |
| end_at | str | Chapter end ISO date |
| text | str | Full chapter arc narrative (the field embedded) |

16 rows (one per chapter). Used for semantic "what does this chapter feel like?" queries.
Tagged `[NARRATIVE]` in Echo Speaks — orientation only, not primary evidence.

### `videos` (lancedb)

| Column | Type | Notes |
|--------|------|-------|
| video_id | str | YouTube video ID |
| title | str | Video title (from video_metadata if available, else watches.title) |
| channel | str | Channel name |
| watch_count | int | How many times watched |
| max_rewatch_count | int | Highest rewatch_count across all watch_signals rows for this video |
| text | str | `"title | channel"` — the field embedded |

5,790 rows (one per unique video). Used for content-level semantic search.
Tagged `[SEMANTIC-RAW]` in Echo Speaks.

### `searches` (lancedb)

| Column | Type | Notes |
|--------|------|-------|
| query | str | YouTube search query |
| count | int | How many times this query appeared |
| first_seen | str | ISO date of first occurrence |
| last_seen | str | ISO date of last occurrence |
| text | str | The query string (the field embedded) |

349 rows (unique YouTube search queries). Used for intent-level semantic search.
Tagged `[SEMANTIC-RAW]` in Echo Speaks.

### `google_searches` (lancedb)

| Column | Type | Notes |
|--------|------|-------|
| query | str | Google search query |
| count | int | How many times this query appeared |
| first_seen | str | ISO date of first occurrence |
| last_seen | str | ISO date of last occurrence |
| text | str | The query string (the field embedded) |

3,211 rows (unique Google search queries). Used for web-intent semantic search.
Tagged `[SEMANTIC-RAW]` in Echo Speaks.

---

## API endpoint response contracts

### `GET /api/insights/sessions`

Query params: `limit` (default 50, max 200), `min_depth` (default 5, min 2).

Returns `{"sessions": [...]}` where each session object has:

| Field | Type | Notes |
|-------|------|-------|
| session_id | int | Sequential session ID (from watch_signals) |
| depth | int | Total videos in session (`session_length`) |
| session_start | str | IST datetime of first watch |
| session_end | str | IST datetime of last watch |
| duration_min | int | Session wall-clock duration in minutes |
| watch_count | int | Actual watch rows in this session |
| top_channel | str | Most-watched channel in this session (nullable) |
| searched_count | int | Watches where `is_search_driven=1` |
| autoplay_count | int | Watches where `is_autoplay=1` |
| rewatch_count | int | Watches where `is_rewatch=1` |
| start_hour | int | IST hour (0–23) session started |
| is_night | bool | True if start_hour ≥ 23 or start_hour < 4 |
| sample_titles | list[str] | First 3 video titles in chronological order |
| shorts_pct | float | % of watches that are Shorts (duration < 60s) |
| depth_pct | float | depth / max_depth * 100 (relative bar chart width) |

### `GET /api/insights/agency`

Returns `{"chapters": [...]}` where each chapter object has:

| Field | Type | Notes |
|-------|------|-------|
| chapter_id | int | chapters.id |
| label | str | "Chapter N" |
| start_at | str | Chapter start ISO date |
| end_at | str | Chapter end ISO date |
| total | int | Total watches in chapter |
| searched | int | Watches where `is_search_driven=1` |
| bookmarked | int | Watches where `was_bookmarked=1` |
| autoplay | int | Watches where `is_autoplay=1` |
| rewatch | int | Watches where `is_rewatch=1` |
| searched_pct | float | searched / total * 100 |
| bookmarked_pct | float | bookmarked / total * 100 |
| autoplay_pct | float | autoplay / total * 100 |
| rewatch_pct | float | rewatch / total * 100 |

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
- **Spotify plays:** 16,678 total across all Extended Streaming History files
