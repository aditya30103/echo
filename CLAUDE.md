# Echo — Project Instructions for Claude Code

## What this project is

Echo is a personal data archaeology project — 6+ years of YouTube watches,
searches, calendar events, transactions, and Spotify plays ingested into
SQLite + LanceDB and analysed by an autonomous Claude-powered agent.
The data spans personal life from age 13 onwards; treat with appropriate care.

**Stack:** Python + FastAPI + SQLite (sqlite-utils) + LanceDB + SvelteKit + Anthropic (Claude)
**License:** MIT (`LICENSE` at repo root)
**Owner:** Aditya Arya (IST timezone)
**Status:** Echo v3 live. Public OSS-release prep in progress (2026-05-16).

---

## Status — packaging shipped, awaiting merge

The `packaging-v1` branch ships the installable `echo` CLI plus every
follow-on (api/ migration, docker mount updates, `echo serve`,
`echo migrate-data`, full README/SETUP/ARCHITECTURE doc trio,
requirements.txt retired in favor of pyproject.toml).

Open queue for the next session (all in `TODOS.md`):
- Fixture-based integration tests (one per pipeline step against a tiny
  hand-crafted Takeout zip under `tests/fixtures/`).
- GitHub Action smoke test (clone → `pip install -e .` → `echo init
  --non-interactive` → `echo run` against the fixture).
- SvelteKit `adapter-static` swap so `echo serve` ships the UI prebuilt.
- Final pytest sanity gate, then merge `packaging-v1` → `master`.
- Spotify Phase 2 (`echo enrich-spotify` full run) when quota unblocks.

Design doc for packaging: `~/.gstack/projects/Echo/Aditya Arya-master-design-packaging-20260516.md`.

---

## Pipeline order

Scripts run in this exact order. Each depends on the previous.

```
ingest → enrich → enrich-spotify → enrich-music-meta → detect → signals → reflect → embed
```

(`enrich-spotify` and `enrich-music-meta` are optional; both are fail-soft on missing keys and `echo run` continues past them.)

See `RUNBOOK.md` for full usage. See `DATA.md` for what every table and column means.

---

## Must-ensure practices (enforce these every session)

### Git hygiene
- **Commit after every meaningful change.** Message explains the WHY, not just
  the what. "Fix calendar date comparison" is bad. "Fix calendar query: start_date
  is raw ICS (YYYYMMDD), not ISO — BETWEEN silently returned 0" is good.
- **Stage specific files** by name, never `git add -A` or `git add .` —
  protects `echo.db`, `_data/`, `private/`, `.env` even if `.gitignore` slips.
- **`Co-Authored-By` matches the active model.** When the user `/model`s mid-
  session, subsequent commits use the new model's attribution, not the default.

### Documentation
- **`DATA.md`** — update whenever a table or column is added, removed, or its
  semantics change. Include how it's computed and known limitations.
- **`RUNBOOK.md`** — update whenever a script is added, pipeline order changes,
  or a new external dependency is required.
- **Constants** — every tunable constant gets an inline comment explaining the
  reasoning and what changes if you adjust it. Not the value — the *why*.
- **Top-of-file docstrings** — every pipeline script self-documents purpose,
  inputs, outputs, idempotency, deps, cost/time. Keep current.

### Code quality
- **All scripts must remain idempotent.** Safe to re-run without data corruption.
  `ingest.py`: UNIQUE constraints. `detect.py`/`signals.py`: DROP + recompute.
  `reflect.py`: appends.
- **IST timezone** — hour/day calculations use `datetime(watched_at, '+330 minutes')`
  (UTC+5:30). Never use raw UTC for behavioral analysis.
- **ICS date format** — `calendar_events.start_date` is raw ICS (`YYYYMMDDTHHMMSSZ`),
  not ISO-8601. Always normalise before comparing:
  `substr(start_date,1,4)||'-'||substr(start_date,5,2)||'-'||substr(start_date,7,2)`
- **`--dry-run` before any `reflect.py` live run** — prompts consume GPT-4o tokens.

### Sensitive data rules
- Data spans personal life from age 13. Don't log, print, or expose specific
  watch titles or search queries unnecessarily.
- `.env`, `echo.db`, `_data/`, `private/`, `AB Test/`, `lancedb/` — all gitignored,
  never commit.
- `.env.example` (no values) is the only env-related file ever committed.
- Personal life context (`private/annotations.yaml`) is per-user, gitignored;
  `annotations.example.yaml` is the public template.

---

## Key files

| File / dir | Purpose |
|------------|---------|
| `ingest.py` | Loads Takeout + Spotify zips into echo.db (8 tables) |
| `enrich.py` | YouTube Data API enrichment (video_metadata) |
| `enrich_spotify.py` | Spotify Web API enrichment (spotify_tracks: duration, explicit, URI verify) |
| `enrich_music_meta.py` | Last.fm tag enrichment (artist + top-N track tags; mood/genre dimension for cross-modal agent queries) |
| `detect.py` | PELT changepoint detection → chapters + chapter_fingerprints |
| `signals.py` | Engagement scoring → watch_signals + spotify_signals |
| `reflect.py` | GPT-4o narrative reflection → reflections (reads private/annotations.yaml) |
| `embed.py` | LanceDB vector embedding → 5 tables (reflections, videos, searches, google_searches, spotify_tracks) |
| `embed_common.py` | Shared embedding utilities (load_env, get_embed_client, ALL_TABLES) |
| `viewer.py` | Static HTML viewer for chapter reflections (proofreading tool) |
| `run.bat` / `run.sh` | One-line Datasette launchers (Windows / *nix) |
| `api/` | FastAPI backend — routers: timeline, chat, insights, speak |
| `api/tools/` | Agent toolkit: sql, python, search, pelt, clustering, youtube, web_search |
| `api/tools/compressors.py` | Per-tool observation compression (Layer 1 context mgmt) |
| `api/llm.py` | LLM routing: Anthropic native → OpenAI → OpenRouter; prompt caching |
| `api/observability.py` | Langfuse tracing wrapper (noop if keys absent) |
| `ui/` | SvelteKit frontend (Echo Speaks landing + Binge Sessions + Agency Map + Ask Echo) |
| `_data/` (gitignored) | Raw Takeout / Spotify zips live here |
| `private/` (gitignored) | Per-user `annotations.yaml` with life context |
| `annotations.example.yaml` | Template — copy to `private/annotations.yaml` to add LIFE CONTEXT |
| `metadata.yaml` | Datasette query definitions (sanitized; no personal refs) |
| `LICENSE` | MIT |
| `DESIGN.md` | Visual design system — two-temperature principle, color tokens, typography, component patterns. Read before touching any UI. |
| `CLAUDE.md` / `AGENTS.md` | AI context (AGENTS.md is a stub; CLAUDE.md is source of truth) |
| `SETUP.md` | Onboarding (will be rewritten in the packaging session) |
| `RUNBOOK.md` | How to operate the pipeline |
| `DATA.md` | What every table and column means |
| `TODOS.md` | Deferred work + active focus pointer |
| `Dockerfile`, `ui/Dockerfile`, `docker-compose.yml` | Container setup |
| `.env` (gitignored) / `.env.example` (committed) | API key configuration |
| `pyproject.toml` | Package metadata + dependencies (canonical; `requirements.txt` retired) |

---

## Session start protocol

1. Run `/context-restore` to load the last checkpoint.
2. Check `git log --oneline -5` to see what was last committed.
3. Check `git status` — if there are uncommitted changes, understand them before proceeding.
4. Read `TODOS.md` — the top entry is usually the active focus.
5. For anything non-trivial, state the approach before executing.

---

## Known gotchas

- `calendar_events.start_date` is raw ICS format — see ICS date format rule above.
- `watch_later` is a snapshot at Takeout export date — `was_bookmarked` reflects
  that snapshot, not the state at watch time.
- `is_autoplay` is a same-channel proxy only. True autoplay rate is higher.
- Calendar data only exists from 2022 onwards. Chapters 1–4 (2019–2021) have no
  calendar context in `reflect.py`. Correct, not a bug.
- `enrich.py` YouTube API quota: 10,000 units/day. On 403, wait for midnight PT.
- `google_searches` pre-2024 data: `is_search_driven` is 0% for pre-2024 watches —
  search-signal tracking only became reliable in 2024. Known artifact.
- `UNSAFE_PYTHON_SANDBOX` must be `"true"` (string) in `.env` to enable
  `execute_python` in the agent. Default `false` returns an error string,
  not an exception.
- Agent Phase 1 (rounds 1–10) blocks the `reflections` lancedb table in both
  `vector_search` dispatch and `run_sql`. Intentional narrative blindness.
- `spotify_plays.ts` timestamp normalization: raw Spotify uses `Z` suffix;
  echo.db elsewhere uses `+00:00`. `Z` sorts AFTER `+00:00` in string comparison,
  silently breaking cross-table joins. Always normalize on ingest:
  `ts = row["ts"].replace("Z", "+00:00")`. SQLite `strftime`/`datetime` handle
  both identically — the normalization is for string-comparison safety only.
- `LANGFUSE_HOST` (NOT `LANGFUSE_BASE_URL`) is the env var name read by
  `api/observability.py`. The other name is silently ignored.

---

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool.

- Product ideas / brainstorming → `/office-hours`
- Strategy / scope → `/plan-ceo-review`
- Architecture → `/plan-eng-review`
- Design system / plan review → `/design-consultation` or `/plan-design-review`
- Full review pipeline → `/autoplan`
- Bugs / errors → `/investigate`
- QA / testing → `/qa` or `/qa-only`
- Code review / diff → `/review`
- Visual polish → `/design-review`
- Ship / deploy / PR → `/ship` or `/land-and-deploy`
- Save progress → `/context-save`
- Resume context → `/context-restore`
