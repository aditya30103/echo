# Echo — Runbook

Operational guide for running and maintaining the Echo pipeline.
For what tables/columns mean, see [DATA.md](./DATA.md).

---

## Prerequisites

```bash
pip install -e .
```

`pyproject.toml` declares every runtime dep (sqlite-utils, ruptures, lancedb,
openai, anthropic, fastapi, uvicorn, typer, ...). The `dev` extra adds pytest:

```bash
pip install -e ".[dev]"
```

API keys live in `~/.echo/.env` (created by `echo init`; the wizard prompts
for each one). For the canonical list and what each is used for, see
[.env.example](./.env.example).

| Key | Required for |
|-----|-------------|
| `YOUTUBE_API_KEY` | `echo enrich` |
| `OPENAI_API_KEY` | `echo embed`, `echo reflect`, agent fallback |
| `OPENROUTER_API_KEY` | reflect / embed / agent alternative path |
| `ANTHROPIC_API_KEY` | Echo Speaks agent (primary; best prompt caching) |
| `SPOTIFY_CLIENT_ID` + `_SECRET` | `echo enrich-spotify` (optional) |
| `LASTFM_API_KEY` | `echo enrich-music-meta` (optional; powers mood/genre dimension and cross-modal agent queries) |
| `SPOTIFY_ZIP` | `echo ingest` — filename of Spotify zip inside `~/.echo/_data/` (defaults to `my_spotify_data.zip`) |
| `UNSAFE_PYTHON_SANDBOX` | Echo Speaks `execute_python` tool (set `"true"` to enable; default `false`) |
| `LANGFUSE_PUBLIC_KEY`, `_SECRET_KEY`, `_HOST` | Echo Speaks observability (all optional; falls back to noop) |
| `ECHO_DATA_DIR` | Override the data dir (defaults to `~/.echo/`) |

---

## Pipeline

Scripts must run in this order. Each step depends on the previous.

```
ingest → enrich → enrich-spotify → enrich-music-meta → detect → signals → reflect → embed
```

| Step | Command | Reads | Writes | Idempotent? |
|------|---------|-------|--------|-------------|
| 1 | `echo ingest` | 3 YouTube/Activity zip files + Spotify zip | watches, yt_searches, watch_later, google_searches, discover_feed, calendar_events, transactions, spotify_plays | Yes — UNIQUE constraints |
| 2 | `echo enrich` | watches | video_metadata | Yes — skips already-fetched videos |
| 2b | `echo enrich-spotify` (optional) | spotify_plays | spotify_tracks (duration_ms, explicit, uri_verified) | Yes — LEFT JOIN skips enriched URIs |
| 2c | `echo enrich-music-meta` (optional) | spotify_tracks, spotify_plays | spotify_tracks (artist_lastfm_tags, lastfm_tags, meta_enriched_at) | Yes — meta_enriched_at filter skips done rows |
| 3 | `echo detect` | watches, video_metadata | chapters, chapter_fingerprints | Yes — drops and recomputes |
| 4 | `echo signals` | watches, yt_searches, watch_later, spotify_plays | watch_signals, spotify_signals | Yes — drops and recomputes |
| 5 | `echo reflect` | all tables | reflections | Yes — appends new rows |
| 6 | `echo embed` | echo.db (5 corpora) | lancedb/ (5 tables: reflections, videos, searches, google_searches, spotify_tracks) | Yes — drops and recreates each table |

### Step 1 — Ingest

```bash
python ingest.py
```

Reads from zip files in `_data/` (gitignored) — paths configured at the top of
`ingest.py` via the `DATA_DIR` and `ZIP_*` constants:

**YouTube / Google Takeout (3 files, in `_data/`):**
- `takeout-<timestamp>-4-001.zip` — YouTube Takeout
- `takeout-<timestamp>-6-001.zip` — My Activity
- `takeout-<timestamp>-3-001.zip` — Calendar + Timeline

**Spotify Extended Streaming History (1 file, optional, in `_data/`):**
- `my_spotify_data.zip` — default filename, configurable via `SPOTIFY_ZIP` env var

Expected output: ~6,280 watches, ~469 searches, ~3,849 calendar events, ~16,678 Spotify plays.
If the Spotify zip is absent, the loader prints a skip message and continues — YouTube data ingests normally.
If adding new Takeout data, drop the zips into `_data/` and update the `ZIP_*`
constants at the top of `ingest.py` to match the new filenames.

### Step 1b — Enrich Spotify (optional)

```bash
python enrich_spotify.py               # enrich all 4,342 unique tracks
python enrich_spotify.py --dry-run     # show pending count, no API calls
python enrich_spotify.py --limit 100   # enrich first 100 (test run)
```

Requires `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in `.env`.
Create a free app at `developer.spotify.com/dashboard` (Client Credentials flow — no user login needed).

Fetches in three passes:
1. `/tracks` (50/batch) → duration_ms, popularity, explicit, artist URI
2. `/artists` (50/batch) → genres (JSON array from primary artist)
3. `/audio-features` (100/batch) → valence, energy, danceability, tempo, key, mode
   — If your app was registered after November 2024, this returns 403. Those columns
   will be NULL; all other metadata is still fetched and stored. Script continues safely.

Safe to interrupt and re-run — already-enriched URIs are skipped.
~4,342 unique tracks → ~90 batch calls → completes in ~3 minutes.

> **Note on Spotify daily quota:** Spotify Web API apps registered after
> November 2024 hit a soft daily ceiling of ~650 search calls. Full
> enrichment of a 4,300-track library takes ~6-7 drip-feed days. The
> batch-flush in `enrich_spotify.py` makes partial progress safe — every
> 50 enriched tracks land in the DB before the next API call, so a quota
> wall mid-run discards nothing.

### Step 1c — Enrich music meta via Last.fm (optional)

```bash
echo enrich-music-meta              # Tier 1 (per-artist) + Tier 2 (top-500 tracks)
echo enrich-music-meta --dry-run    # show counts, no API calls
echo enrich-music-meta --top-n 1000 # deeper Tier 2 coverage
echo enrich-music-meta --top-n 0    # Tier 1 only, skip Tier 2
```

Requires `LASTFM_API_KEY` in `.env`. Register a free app at
`last.fm/api/account/create` (instant, no review).

Two tiers:
1. **Tier 1 (per-artist):** Fetches top community tags for every unique
   artist in `spotify_tracks`. ~400-500 calls. Writes `artist_lastfm_tags`
   to all rows for each artist.
2. **Tier 2 (per-track, top-N):** Fetches top tags for the N most-played
   tracks (default 500). Writes `lastfm_tags` to those rows.

The agent's `vector_search` over the new lancedb `spotify_tracks` table
uses track-level tags when present, falls back to artist-level. This is
what powers cross-modal queries like "when was I in a melancholy phase
and what was I watching at the same time?"

Fail-soft on missing key: if `LASTFM_API_KEY` is unset, the step prints
a setup link and continues to the next pipeline step (no `sys.exit(1)`).

### Step 2 — Enrich YouTube

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

Computes per-watch and per-play engagement signals. No arguments needed.
Re-running drops and rewrites both `watch_signals` (YouTube) and `spotify_signals` (Spotify, if `spotify_plays` table exists).
Expected output: 6,280 watch signals across ~1,100 sessions; 16,678 Spotify signals across 2,165 sessions.

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

`private/annotations.yaml` holds date-range-tagged clarifications about
real-life events that the data alone can't reveal (school name, illness,
job change, mislabeled calendar entries). reflect.py reads this file at
prompt-build time and injects matching entries into the `LIFE CONTEXT`
section of each chapter prompt.

The `private/` directory is gitignored so your personal context stays local.
Copy `annotations.example.yaml` (at repo root) to `private/annotations.yaml`
and fill in your own entries. reflect.py runs fine without the file — you
just lose the LIFE CONTEXT injection. Add entries whenever a chapter
reflection misinterprets what the data represents.

### Step 6 — Embed (Layer 4)

```bash
python embed.py                           # embed all 4 tables
python embed.py --dry-run                 # show counts and sample texts, no API calls
python embed.py --table reflections       # embed one table only
python embed.py --table videos
python embed.py --table searches
python embed.py --table google_searches
```

Embeds 4 corpora into a local lancedb vector index at `./lancedb/`:

| lancedb table | Source | Rows | Text field |
|---------------|--------|------|------------|
| `reflections` | reflections (kind='chapter') | 16 | Chapter arc narrative |
| `videos` | watches + video_metadata | 5,790 | "title \| channel" |
| `searches` | yt_searches (unique queries) | 349 | YouTube search query |
| `google_searches` | google_searches (unique queries) | 3,211 | Google search query |

Model: `text-embedding-3-small` (1536 dims). Prefers `OPENAI_API_KEY`, falls back to
`OPENROUTER_API_KEY`. Idempotent — drops and recreates each table on every run.
Must re-run after reflect.py if chapter reflections change.

---

## Echo UI (v2 — FastAPI + SvelteKit)

Run both servers concurrently (two terminals):

```bash
# Terminal 1 — FastAPI backend (port 8000)
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000

# Terminal 2 — SvelteKit dev server (port 5173)
cd ui && npm run dev
```

Open http://localhost:5173

The Vite dev server proxies all `/api` requests to the FastAPI backend.
No CORS configuration needed — both run on localhost.

### API endpoints

#### Timeline

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Liveness check |
| `/api/timeline?month=YYYY-MM&limit=200&offset=0` | GET | Watches for a given month, paginated |
| `/api/timeline/night` | GET | All 11 PM – 4 AM IST watches (~1,097 rows) |

#### Chapters & Search

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chapters` | GET | All 16 chapters with fingerprints and reflections |
| `/api/search?q=...&tables=videos,searches,google_searches,reflections&limit=10` | GET | Semantic search across lancedb tables |

#### Psyche Diff

| Endpoint | Method | Body | Description |
|----------|--------|------|-------------|
| `/api/diff/chapters` | GET | — | Chapter list for diff selector |
| `/api/diff` | POST | `{"chapter_a": 1, "chapter_b": 2, "model": "auto"}` | LLM narrative comparing two chapters |

#### Ask Echo (RAG chat)

| Endpoint | Method | Body | Description |
|----------|--------|------|-------------|
| `/api/chat/models` | GET | — | Available LLM providers |
| `/api/chat` | POST | `{"question": "...", "model": "auto", "include_chapters": false}` | RAG chatbot over behavioral data |

`include_chapters` defaults to `false` — chapter arc narratives dominated answers and
drowned out raw signals. Leave off unless specifically asking about chapter arcs.

#### Insights

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/insights/sessions` | GET | Top 50 binge sessions (≥5 videos) ranked by depth |
| `/api/insights/agency` | GET | Per-chapter agency breakdown: searched / bookmarked / autoplay / rewatch |

#### Echo Speaks (agentic)

| Endpoint | Method | Body | Description |
|----------|--------|------|-------------|
| `/api/speak` | POST | `SpeakRequest` | Non-streaming: full JSON response after all rounds |
| `/api/speak/stream` | POST | `SpeakRequest` | SSE streaming: events emitted per round as they happen |

`SpeakRequest` fields:

| Field | Default | Description |
|-------|---------|-------------|
| `query` | required | What to investigate |
| `model` | `"auto"` | `"auto"` / `"claude"` / `"gpt4o"` |
| `max_rounds` | `20` | Maximum ReAct rounds before forced synthesis |
| `narrative_blind_rounds` | `10` | Phase 1 length — reflections/chapter context blocked until this round |

SSE event types: `rubric_start`, `rubric_done`, `round_start`, `phase_change`,
`thought`, `action`, `observation`, `finish`, `error`, `format_error`.

### Smoke checks

```bash
# health
curl http://127.0.0.1:8000/api/health

# chapters — expect 16
curl http://127.0.0.1:8000/api/chapters | python -c "import sys,json; d=json.load(sys.stdin); print(d['total'], 'chapters')"

# night watches — expect ~1097
curl http://127.0.0.1:8000/api/timeline/night | python -c "import sys,json; d=json.load(sys.stdin); print(d['total'], 'rows')"

# semantic search
curl "http://127.0.0.1:8000/api/search?q=music&tables=videos&limit=3"

# insights
curl http://127.0.0.1:8000/api/insights/sessions | python -c "import sys,json; d=json.load(sys.stdin); print(len(d['sessions']), 'sessions')"
curl http://127.0.0.1:8000/api/insights/agency | python -c "import sys,json; d=json.load(sys.stdin); print(len(d['chapters']), 'chapters')"

# echo speaks (non-streaming)
curl -X POST http://127.0.0.1:8000/api/speak \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"What are the top 5 channels I watch?\", \"max_rounds\": 5}"
```

---

## Echo Speaks — Observability (Langfuse)

Echo Speaks traces every agent run to Langfuse. If `LANGFUSE_PUBLIC_KEY` and
`LANGFUSE_SECRET_KEY` are in `.env`, traces appear at `https://cloud.langfuse.com`
automatically. If keys are absent, tracing is a silent no-op.

Each trace contains:
- One root `echo-speaks` agent span (input = query, output = findings summary)
- Per-round generation spans (`round-N`): model, token counts (input + output), truncated response
- Per-round tool spans (`tool-<name>`): tool arguments, observation excerpt, source tag

Token counts are emitted for every generation span, enabling per-query cost tracking
in the Langfuse dashboard.

To set up Langfuse: create a free project at `https://cloud.langfuse.com`, copy the
public and secret keys into `.env`. No other configuration needed.

---

## Browsing the data (Datasette — legacy)

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

### New Spotify export

1. Request a new Extended Streaming History export from Spotify account settings (takes ~30 days).
2. Place the downloaded zip in `_data/` as `my_spotify_data.zip`, or set
   `SPOTIFY_ZIP=<filename_inside_data_dir>.zip` in `.env`.
3. Re-run `python ingest.py`. The UNIQUE constraint prevents duplicates — new plays are appended.

The Spotify zip is auto-detected by file name pattern `Streaming_History_Audio_*.json` and
`Streaming_History_Video_*.json` inside the archive. Year files overlap (e.g. Audio_2024 and
Audio_2025 share late December 2024) — the UNIQUE index handles deduplication automatically.

---

## Troubleshooting

**`ModuleNotFoundError`**
```bash
pip install -e ".[dev]"
```

**`enrich.py` quota exhausted (HTTP 403)**
YouTube API quota resets at midnight Pacific. Re-run the next day — it skips already-fetched videos.

**DB looks wrong after a failed run**
`ingest.py`, `detect.py`, and `signals.py` are all idempotent — just re-run from the failing step.

**`reflect.py` — no reflections appearing**
Check that `OPENAI_API_KEY` or `OPENROUTER_API_KEY` is set in `.env`. Run with `--dry-run` first.

**`embed.py` — lancedb table missing / search returns nothing**
Re-run `python embed.py` to rebuild all 4 tables. Must be done after reflect.py if reflections changed.

**Echo Speaks — agent hits round limit without synthesizing**
Increase `max_rounds` in the request body (default 20). Check Langfuse traces to see which
rounds were wasted on schema exploration — the system prompt should pre-empt this via
`_fetch_schema_context()`, but very complex queries may still need more rounds.

**Echo Speaks — Langfuse not receiving traces**
Check `.env` has both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`.
The API server log will print `[observability] Langfuse connected: ...` on startup if keys are valid.

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
| `SPOTIFY_SESSION_GAP_MIN` | signals.py | 30 | Minutes between Spotify plays that starts a new session |
| `BATCH_SIZE` | embed.py | 512 | Inputs per embeddings API call (OpenAI hard limit: 2048) |
| `max_rounds` | speak.py | 20 | Default ReAct rounds for Echo Speaks |
| `narrative_blind_rounds` | speak.py | 10 | Rounds before chapter reflections are available to agent |
| `_KEEP_FULL_ROUNDS` | speak.py | 4 | Rounds of full observation kept in agent context window |

See inline comments in each script for reasoning behind each value.
