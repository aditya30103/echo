# Echo — Runbook

Operational guide for running and maintaining the Echo pipeline.
For what tables/columns mean, see DATA.md.

---

## Prerequisites

```
pip install sqlite-utils ruptures numpy matplotlib openai
```

API keys go in `.env` (copy `.env.example` and fill in values):
- `YOUTUBE_API_KEY` — required for enrich.py
- `OPENAI_API_KEY` or `OPENROUTER_API_KEY` — required for reflect.py (OpenRouter used as fallback)

---

## Pipeline

Scripts must run in this order. Each step depends on the previous.

```
ingest.py → enrich.py → detect.py → signals.py → reflect.py
```

| Step | Script | Reads | Writes | Idempotent? |
|------|--------|-------|--------|-------------|
| 1 | `ingest.py` | 3 zip files | watches, yt_searches, watch_later, google_searches, discover_feed, calendar_events, transactions | Yes — UNIQUE constraints |
| 2 | `enrich.py` | watches | video_metadata | Yes — skips already-fetched videos |
| 3 | `detect.py` | watches, video_metadata | chapters, chapter_fingerprints | Yes — drops and recomputes |
| 4 | `signals.py` | watches, yt_searches, watch_later | watch_signals | Yes — drops and recomputes |
| 5 | `reflect.py` | all tables | reflections | Yes — appends new rows |

### Step 1 — Ingest

```bash
python ingest.py
```

Reads from the three Takeout zip files hardcoded in `ingest.py`:
- `takeout-20260512T160253Z-4-001.zip` — YouTube Takeout
- `takeout-20260512T160253Z-6-001.zip` — My Activity
- `takeout-20260512T161750Z-3-001.zip` — Calendar + Timeline

Expected output: ~6,280 watches, ~469 searches, ~3,849 calendar events.
If adding new Takeout data, update the `ZIP_*` constants at the top of `ingest.py`.

### Step 2 — Enrich

```bash
python enrich.py
```

Calls YouTube Data API to fetch video metadata (category, duration, channel).
Requires `YOUTUBE_API_KEY` in `.env`.
Safe to interrupt and re-run — skips already-fetched videos.
~5,568 videos available (222 are deleted/private and will show `available=0`).

### Step 3 — Detect (Layer 2)

```bash
python detect.py                  # default penalty=2, writes to DB
python detect.py --penalty 3      # tune: higher = fewer chapters
python detect.py --dry-run        # preview chapters without writing
python detect.py --plot           # save weekly_signal.png
```

Runs PELT changepoint detection on 8-dimensional weekly signal.
Current configuration: penalty=2 → 16 chapters (2020–2026).
Re-running with a different penalty is safe — drops and rewrites chapters + chapter_fingerprints.

### Step 4 — Signals

```bash
python signals.py
```

Computes per-watch engagement signals. No arguments needed.
Re-running drops and rewrites the entire watch_signals table.

### Step 5 — Reflect (Layer 3)

```bash
python reflect.py --dry-run                    # print prompts, no API call
python reflect.py --dry-run --chapter 15       # preview one chapter
python reflect.py --chapter 5                  # reflect on chapter 5 only
python reflect.py                              # reflect on all 16 chapters
python reflect.py --autobiography              # full arc synthesis
```

Requires `OPENAI_API_KEY` or `OPENROUTER_API_KEY` in `.env` (except `--dry-run`).
Results append to the `reflections` table — re-running adds new rows without deleting old ones.
Preview with `--dry-run` before running live to check prompt quality.

#### Life context annotations

`annotations.yaml` holds date-range-tagged clarifications about real-life events
(e.g. "these [McK] calendar entries are prior institution POR events, not McKinsey work").
reflect.py reads this file at prompt-build time and injects matching entries into
the `LIFE CONTEXT` section of each chapter prompt. Add entries here whenever a
chapter reflection misinterprets what the data represents.

---

## Browsing the data

```bash
run.bat           # launches Datasette at http://127.0.0.1:8001
# or
datasette echo.db
```

17 canned queries are defined in `metadata.yaml`.

---

## Adding new data

### New YouTube Takeout export

1. Download a new Takeout zip (YouTube + My Activity).
2. Update `ZIP_YT` and/or `ZIP_ACTIVITY` constants in `ingest.py`.
3. Re-run the full pipeline from Step 1. UNIQUE constraints prevent duplicates.

### Spotify (pending — data expected ~2026-05-17)

Will require a new loader function in `ingest.py` and a new table.
Schema TBD once the export format is known.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'ruptures'`**
```bash
pip install ruptures
```

**`enrich.py` quota exhausted (HTTP 403)**
YouTube API quota resets at midnight Pacific. Re-run the next day — it skips already-fetched videos.

**DB looks wrong after a failed run**
`ingest.py`, `detect.py`, and `signals.py` are all idempotent — just re-run from the failing step.

**`reflect.py` — no reflections appearing**
Check that `OPENAI_API_KEY` or `OPENROUTER_API_KEY` is set in `.env`. If both are set, `OPENAI_API_KEY` takes priority. Run with `--dry-run` first to confirm prompts look right.

---

## Key constants (tunable)

| Constant | File | Value | Meaning |
|----------|------|-------|---------|
| `DEFAULT_PENALTY` | detect.py | 2 | PELT penalty — lower = more chapters |
| `MIN_CHAPTER_WKS` | detect.py | 8 | Minimum chapter length in weeks |
| `MIN_WATCHES` | detect.py | 3 | Sparse week threshold (below = interpolated) |
| `SESSION_GAP_MIN` | signals.py | 30 | Minutes between watches that starts a new session |
| `SEARCH_WIN_MIN` | signals.py | 10 | Search window before watch for is_search_driven |
| `AUTOPLAY_GAP_MIN` | signals.py | 3 | Max gap (min) for same-channel autoplay proxy |

See inline comments in each script for reasoning behind each value.
