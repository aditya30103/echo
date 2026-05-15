# Echo Setup Guide

Echo is a personal data archaeology project — it ingests your Google Takeout export,
runs changepoint detection on your watch history, and gives you an autonomous AI agent
(Echo Speaks) that can answer questions about your behavioral patterns.

---

## What you need

| Requirement | Notes |
|-------------|-------|
| Python 3.11+ | 3.11 recommended; 3.12 works |
| Node.js 20+ | For the Svelte UI |
| Google Takeout export | YouTube History + Search History |
| Anthropic API key | For Claude (recommended). OpenAI or OpenRouter also work. |
| Langfuse account | Optional — for eval tracking. Skipped silently if not configured. |
| YouTube Data API key | Optional — for video metadata enrichment |

---

## Quickstart (local, no Docker)

### 1. Clone and install

```bash
git clone <repo-url>
cd Echo
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux
pip install -r requirements.txt
```

### 2. Configure environment

```bash
copy .env.example .env        # Windows
# cp .env.example .env        # macOS / Linux
```

Edit `.env` and fill in your keys:

```env
ANTHROPIC_API_KEY=sk-ant-...      # Required for Claude (recommended)
OPENAI_API_KEY=sk-...             # Alternative to Anthropic
OPENROUTER_API_KEY=sk-or-...      # Alternative to both

YOUTUBE_API_KEY=AIza...           # Optional: video metadata enrichment
LANGFUSE_PUBLIC_KEY=pk-lf-...     # Optional: eval tracking
LANGFUSE_SECRET_KEY=sk-lf-...     # Optional: eval tracking
LANGFUSE_HOST=https://cloud.langfuse.com

UNSAFE_PYTHON_SANDBOX=false       # Set to true only in trusted environments
```

### 3. Prepare your data

Export your Google data from https://takeout.google.com — select:
- YouTube and YouTube Music → History (watch history + search history)
- (Optional) Google Search History

Place the downloaded zip(s) in `_data/` at the project root (create it if missing —
the directory is gitignored so your raw exports never get accidentally committed).
The expected filenames are whatever Google names them (e.g. `takeout-20240101-001.zip`).
Edit `ZIP_YT`, `ZIP_ACTIVITY`, `ZIP_CALENDAR` near the top of `ingest.py` to match
your filenames.

### 4. Run the ingestion pipeline

Run scripts in this exact order. Each depends on the previous.

```bash
python ingest.py          # Load all data sources into echo.db
python enrich.py          # YouTube Data API enrichment (optional, needs YOUTUBE_API_KEY)
python detect.py          # PELT changepoint detection → chapters table
python signals.py         # Engagement scoring → watch_signals table
```

`reflect.py` is for chapter reflections (GPT-4o narrative). Run after the above:

```bash
python reflect.py --dry-run --chapter 15   # Preview before using tokens
python reflect.py --chapter 15             # Actually generate
```

### 5. Start the API and UI

```bash
# Terminal 1 — API
uvicorn api.main:app --reload --port 8000

# Terminal 2 — UI
cd ui
npm install
npm run dev
```

Open http://localhost:5173 in your browser.

---

## Docker Compose (recommended for sharing)

Prerequisites: Docker Desktop installed and running.

```bash
# Copy and fill in your .env file first (see step 2 above)
docker compose up --build
```

This starts:
- API on http://localhost:8000 (mounts your `echo.db` and `.env` read-only)
- UI on http://localhost:5173

To stop: `docker compose down`

**Note:** `echo.db` must exist before running `docker compose up`. Run the ingestion
pipeline locally first (steps 3–4 above), then use Docker for the API + UI.

---

## Security model

### UNSAFE_PYTHON_SANDBOX

Echo Speaks can execute Python code via the `execute_python` tool. This is disabled
by default (`UNSAFE_PYTHON_SANDBOX=false`). If you enable it, the agent can run
arbitrary Python in the server process with no sandboxing.

**Only enable in trusted local environments where you are the only user.**

Docker Compose sets `UNSAFE_PYTHON_SANDBOX=false` by default. Do not override this
if exposing Echo on a network.

### Personal data

`echo.db` contains your full watch history, search history, calendar events, and
transactions. It is `.gitignore`d and should never be committed or shared.

---

## Running tests

```bash
pytest tests/ -v
```

Tests use the live `echo.db` for integration tests (PELT, clustering). They require
the pipeline to have been run at least through `detect.py`. Tests that hit external
APIs are mocked.

---

## Troubleshooting

**`No LLM API key found`** — Check your `.env` file. Run `python -c "from embed_common import load_env; load_env(); import os; print(os.environ.get('ANTHROPIC_API_KEY','missing'))"` to verify it loads.

**`enrich.py` hits 403 from YouTube API** — You've hit the 10,000 unit/day quota. Wait for midnight PT for reset.

**`echo.db` not found in Docker** — Make sure `echo.db` exists in the project root before running `docker compose up`. The container mounts it read-only.

**Langfuse scores not appearing** — Check `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` in `.env`. The server logs `[observability] Langfuse connected` on startup if keys are valid.

**`calendar_events` has no data** — Calendar data in Google Takeout only covers 2022 onwards. Chapters 1–4 (2019–2021) have no calendar context — this is expected.
