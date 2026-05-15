# Echo — Project Instructions for Claude Code

## What this project is

Echo is a deeply personal data archaeology project — 6+ years of Aditya's digital life
(YouTube watches, searches, calendar, transactions) ingested into a SQLite database and
analysed by an autonomous AI agent. The data spans ages 13–23.
Treat insights from it with appropriate weight. This is not a demo project.

**Owner:** Aditya Arya (23, Indian, IST timezone)
**Stack:** Python + FastAPI + SQLite (sqlite-utils) + LanceDB + SvelteKit + Anthropic (Claude)
**DB:** `D:\Projects\Echo\echo.db` — never committed to git (personal data)
**Version:** Echo v3 — all sprints shipped (2026-05-15)

---

## Pipeline order

Scripts must run in this exact order. Each depends on the previous.

```
ingest.py → enrich.py → detect.py → signals.py → reflect.py → embed.py
```

See RUNBOOK.md for full usage. See DATA.md for what every table and column means.

---

## Must-ensure practices (enforce these every session)

### Git hygiene
- **Commit after every meaningful script change.** Message must explain the WHY,
  not just the what. "Fix calendar date comparison" is bad. "Fix calendar query:
  start_date is raw ICS format (YYYYMMDD), not ISO — BETWEEN was silently returning 0" is good.
- **Never stage:** `echo.db`, `*.zip`, `.env`, `early_entries.txt`, `weekly_signal.png`
  — all in `.gitignore`. Double-check before committing.
- **Stage specific files** by name, never `git add -A` or `git add .`

### Documentation
- **DATA.md** — update whenever a table or column is added, removed, or its semantics change.
  Include how it's computed and known limitations.
- **RUNBOOK.md** — update whenever a new script is added, pipeline order changes,
  or a new external dependency is required.
- **Constants** — every tunable constant in every script gets an inline comment explaining
  the reasoning and what changes if you adjust it. Not the value — the *why*.

### Code quality
- **All scripts must remain idempotent.** Safe to re-run without data corruption.
  ingest.py: UNIQUE constraints. detect.py/signals.py: DROP + recompute. reflect.py: appends.
- **IST timezone** — all hour/day calculations use `datetime(watched_at, '+330 minutes')` (UTC+5:30).
  Never use raw UTC for behavioral analysis.
- **ICS date format** — `calendar_events.start_date` is stored as raw ICS (`YYYYMMDDTHHMMSSZ`),
  not ISO-8601. Always normalise before comparing:
  `substr(start_date,1,4)||'-'||substr(start_date,5,2)||'-'||substr(start_date,7,2)`
- **Use `--dry-run` before any reflect.py live run** — prompts consume GPT-4o tokens.
  Always preview first.

### Sensitive data rules
- The data spans Aditya's personal life from age 13. Do not log, print, or expose
  specific watch titles or search queries unnecessarily.
- `.env` is never committed. `.env.example` (no values) is.
- If Spotify data arrives, treat it with the same sensitivity as watch history.

---

## Key files

| File | Purpose |
|------|---------|
| `ingest.py` | Loads all data sources from Takeout zip files into echo.db |
| `enrich.py` | YouTube Data API enrichment (video metadata) |
| `detect.py` | PELT changepoint detection → chapters + chapter_fingerprints tables |
| `signals.py` | Engagement scoring → watch_signals table |
| `reflect.py` | GPT-4o narrative reflection → reflections table |
| `embed.py` | LanceDB vector embedding → 4 tables (videos, searches, google_searches, reflections) |
| `embed_common.py` | Shared embedding utilities (load_env, get_embedding) |
| `api/` | FastAPI backend — routers: timeline, chat, insights, speak |
| `api/tools/` | Agent toolkit: sql, python, search, pelt, clustering, youtube, web_search |
| `api/llm.py` | LLM routing: Anthropic native → OpenAI direct → OpenRouter fallback; prompt caching |
| `api/observability.py` | Langfuse tracing wrapper (noop if keys absent) |
| `ui/` | SvelteKit frontend — Echo Speaks landing + Binge Sessions + Agency Map + Ask Echo |
| `SETUP.md` | Full onboarding guide (data ingestion → running Echo) |
| `TODOS.md` | Deferred work items with context for pickup |
| `RUNBOOK.md` | How to operate the pipeline |
| `DATA.md` | What every table and column means |
| `Dockerfile` | API container (python:3.11-slim, port 8000) |
| `ui/Dockerfile` | UI container (node:20-alpine, port 5173) |
| `docker-compose.yml` | Two-container setup; mounts echo.db + .env read-only |
| `.env` | API keys — never committed |
| `.env.example` | API key template — always keep current |
| `requirements.txt` | Python dependencies — keep in sync with actual imports |

---

## Session start protocol

At the start of any session:
1. Run `/context-restore` to load the last checkpoint.
2. Check `git log --oneline -5` to see what was last committed.
3. Check `git status` — if there are uncommitted changes, understand them before proceeding.
4. For anything non-trivial, state the approach before executing.

---

## Known gotchas

- `calendar_events.start_date` raw ICS format — see ICS date format rule above.
- `watch_later` is a snapshot at Takeout export date — `was_bookmarked` reflects that
  snapshot, not the state at watch time.
- `is_autoplay` is a same-channel proxy only. True autoplay rate is higher.
- Calendar data only exists from 2022 onwards. Chapters 1–4 (2019–2021) have no calendar
  context in reflect.py. This is correct, not a bug.
- `enrich.py` YouTube API quota: 10,000 units/day. If it hits 403, wait for midnight PT reset.
- `google_searches` pre-2024 data: `is_search_driven` is 0% for pre-2024 watches — search
  signal tracking only became reliable in 2024. Known artifact, not a pipeline bug.
- `UNSAFE_PYTHON_SANDBOX` must be `true` (string) in `.env` to enable execute_python in the
  agent. Default is `false` — the tool returns an error string, not an exception.
- Agent Phase 1 (rounds 1–10) blocks the `reflections` lancedb table in both `vector_search`
  dispatch and `run_sql` (reflections table check). This is intentional narrative blindness.
- `spotify_plays.ts` timestamp normalization: raw Spotify data uses `Z` suffix
  (`"2025-05-07T10:00:00Z"`); all other echo.db timestamps use `+00:00` suffix. `Z` (ASCII 90)
  sorts AFTER `+00:00` in string comparison, silently breaking cross-table timestamp comparisons.
  Always normalize on ingest: `ts = row["ts"].replace("Z", "+00:00")`. SQLite strftime/datetime
  handle both formats identically — the normalization is for string-comparison safety only.

---

## Pending (as of 2026-05-15)

- **Echo Speaks context management overhaul** — layered redesign of `_trim_history`.
  Layer 0 (housekeeping) SHIPPED 2026-05-15 in commit `3e53091`. Layer 1 (per-tool
  structured compression in `api/tools/compressors.py`) SHIPPED 2026-05-15 — replaces
  the `[:200]` truncation with semantic per-tag compressors (SQL/Python/vsearch/
  external/narrative). Real-world result: 1892-char SQL observation → 165-char
  compressed (~11x reduction) while preserving columns, first/last row, and row count.
  Layers 2 (heuristic scratchpad) and 3 (Haiku summarization for >25 round runs)
  deferred to their own design reviews. Full analysis: `CONTEXT_MGMT_ANALYSIS.md`.
- **Spotify Phase 2** — `enrich_spotify.py` (Spotify API → `spotify_tracks`: duration_ms, genres,
  valence, energy, danceability, tempo, acousticness, instrumentalness, loudness, mode, key).
  Requires `SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET` in `.env`. Audio features endpoint
  deprecated for apps registered after Nov 2024 — requires pre-Nov 2024 app or NULL fallback.
- **Spotify Phase 3b** — extend `embed.py` with `embed_spotify_tracks()` → LanceDB `spotify_tracks`
  table and wire into agent `vector_search`. Blocked by Phase 2 (needs enriched track names to embed).
- **LLM-as-judge eval batch** — after 20+ human-annotated traces via Echo Speaks score buttons.
  Details in `TODOS.md`. OpenAI key now available.
- **DeepSeek/Ollama routing** — low urgency. Add model slug to `api/llm.py`, point at local
  Ollama via `OPENROUTER_BASE_URL`. Same interface as current OpenRouter path.

## Echo v3 — what's live

Echo Speaks is the primary product. The autonomous ReAct agent (POST /api/speak) runs up to
20 rounds, uses a 7-tool data scientist toolkit, and streams findings back to the UI.

**API routes:** timeline, chat, insights, speak — all active. diff, chapters (static), search
tabs are deprecated and removed.

**UI tabs:** Echo Speaks (landing) · Binge Sessions · Agency Map · Ask Echo (RAG demo)

**Model toggle:** Echo Speaks UI has an Auto / Claude / GPT-4o toggle in the query controls.
`auto` prefers Claude when `ANTHROPIC_API_KEY` is set. `gpt4o` routes directly to OpenAI
(`OPENAI_API_KEY`). Both keys are now configured.

**Agent tools:** run_sql, execute_python (full DS sandbox: numpy/pandas/scipy/sklearn/ruptures),
vector_search, run_pelt, run_clustering, youtube_lookup, web_search (5 calls/session)

**Observability:** Langfuse tracing per session. Per-finding human evals via score buttons
(✓ Correct / ~ Partial / ✗ Wrong) → `finding_N` scores on the Langfuse trace.

**Prompt caching:** Two cache checkpoints on the Anthropic native path.
- Block 1 (`cached_prefix`: schema + rubric + stats) — stable across all rounds → cache hit from round 2.
- Block 2 (instructions: phase rules + tools) — stable within each phase → cache hit from round 2.
  At the Phase 1→2 boundary, Block 2 content changes (tool list expands). That round pays the 1.25×
  write rate for Block 2 once; all subsequent Phase 2 rounds hit the cache at 0.10×. This is expected
  behavior, not a bug — Anthropic's cache never serves stale content on a miss.
Note: an earlier engineering review (Sprint 5 /plan-eng-review Codex subagent) struck down Block 2
caching, incorrectly treating the Phase 2 miss as a cache invalidation risk. Block 2 caching was
restored after confirming Anthropic's miss-is-a-write semantics.

**Docker:** `docker compose up` starts api:8000 + ui:5173. echo.db + .env mounted read-only.

**Security:** `UNSAFE_PYTHON_SANDBOX=false` by default. Must be set `true` to enable
execute_python. Docker Compose does not override this.

---

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool.

- Product ideas/brainstorming → `/office-hours`
- Strategy/scope → `/plan-ceo-review`
- Architecture → `/plan-eng-review`
- Design system/plan review → `/design-consultation` or `/plan-design-review`
- Full review pipeline → `/autoplan`
- Bugs/errors → `/investigate`
- QA/testing → `/qa` or `/qa-only`
- Code review/diff → `/review`
- Visual polish → `/design-review`
- Ship/deploy/PR → `/ship` or `/land-and-deploy`
- Save progress → `/context-save`
- Resume context → `/context-restore`
