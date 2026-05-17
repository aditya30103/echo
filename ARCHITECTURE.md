# Echo architecture

High-level map of what's in the repo, how the pieces fit together, and the
reasoning behind the major technology choices. For installation, see
[SETUP.md](./SETUP.md). For what every table column means, see [DATA.md](./DATA.md).
For day-to-day operation, see [RUNBOOK.md](./RUNBOOK.md).

---

## Mission

Echo is a **personal data archaeology** tool. It takes 6+ years of one
person's Google Takeout (YouTube history, searches, calendar, payments) plus
Spotify Extended Streaming History and turns them into a queryable local store
that an autonomous Claude agent can reason over. The agent finds chapters in
your life from changepoints in your viewing patterns, writes narrative
reflections of each one, and answers free-form questions with evidence trails
back to the underlying rows.

Three rails the architecture commits to:

1. **Local-only.** No SaaS, no hosted version, no telemetry. Your data lives in
   `~/.echo/`; deleting that directory uninstalls Echo from your life.
2. **Reproducible pipeline.** Every step is idempotent. Re-runs are cheap, partial
   re-runs are first-class, and the database schema is the single source of truth
   for what was computed when.
3. **Agent over static analysis.** The Echo Speaks ReAct agent replaces the
   v1/v2 "static report" pages. Every query gets a fresh investigation with the
   actual data the agent looked up, not a pre-baked summary.

---

## Data flow

```
                            ┌──────────────────────────────────────────┐
                            │           Source archives                │
                            │  (Google Takeout zips, Spotify export)   │
                            └──────────────────────────────────────────┘
                                              │
                                              ▼
                            ┌──────────────────────────────────────────┐
   Pipeline                 │      echo.pipeline.ingest                │
   (echo run)               │  (UNIQUE-constraint dedup on every       │
                            │   table; safe to re-run)                 │
                            └──────────────────────────────────────────┘
                                              │
                                              ▼
                            ┌──────────────────────────────────────────┐
                            │      echo.pipeline.enrich                │
                            │  (YouTube Data API; persistent           │
                            │   video_metadata cache)                  │
                            └──────────────────────────────────────────┘
                                              │
                                              ▼
                            ┌──────────────────────────────────────────┐
                            │      echo.pipeline.detect                │
                            │  (PELT changepoint detection on weekly   │
                            │   z-scored signals → chapters +          │
                            │   chapter_fingerprints)                  │
                            └──────────────────────────────────────────┘
                                              │
                                              ▼
                            ┌──────────────────────────────────────────┐
                            │      echo.pipeline.signals               │
                            │  (per-watch + per-spotify-play           │
                            │   engagement scoring)                    │
                            └──────────────────────────────────────────┘
                                              │
                                              ▼
                            ┌──────────────────────────────────────────┐
                            │      echo.pipeline.reflect               │
                            │  (GPT-4o per-chapter + autobiography     │
                            │   narrative; reads private/annotations)  │
                            └──────────────────────────────────────────┘
                                              │
                                              ▼
                            ┌──────────────────────────────────────────┐
                            │      echo.pipeline.embed                 │
                            │  (text-embedding-3-small → 4 LanceDB     │
                            │   tables: reflections, videos,           │
                            │   searches, google_searches)             │
                            └──────────────────────────────────────────┘
                                              │
                                              ▼
                            ┌──────────────────────────────────────────┐
                            │        ~/.echo/echo.db (SQLite)          │
                            │        ~/.echo/lancedb/ (vectors)        │
                            └──────────────────────────────────────────┘
                                              │
        ┌─────────────────────────────────────┼─────────────────────────────────────┐
        │                                     │                                     │
        ▼                                     ▼                                     ▼
┌────────────────┐                  ┌────────────────────┐                ┌─────────────────┐
│ api/  (FastAPI)│                  │ ui/  (SvelteKit)   │                │ datasette       │
│  routers:      │ ◄── /api/* ──    │  Echo Speaks       │                │ (run.sh/.bat)   │
│  speak / chat /│                  │  Binge Sessions    │                │  raw SQL +      │
│  insights /    │                  │  Agency Map        │                │  metadata.yaml  │
│  timeline      │                  │  Ask Echo          │                │  canned queries │
└────────────────┘                  └────────────────────┘                └─────────────────┘
        ▲                                     ▲
        │                                     │
        │            ┌────────────────────────┴─┐
        │            │ echo serve (single port) │
        └────────────┤  FastAPI + StaticFiles   │
                     │  baked UI at port 8000   │
                     └──────────────────────────┘
```

---

## Module map

```
echo/                             # The repo
├── pyproject.toml                # hatchling build, deps, entry point
├── src/
│   └── echo/                     # The installable Python package
│       ├── __init__.py           # version
│       ├── config.py             # EchoConfig dataclass + TOML/.env loader
│       ├── data/
│       │   └── paths.py          # ~/.echo/ resolution (honors $ECHO_DATA_DIR)
│       ├── pipeline/             # The 7 pipeline steps (run(config) each)
│       │   ├── ingest.py
│       │   ├── enrich.py
│       │   ├── enrich_spotify.py
│       │   ├── detect.py
│       │   ├── signals.py
│       │   ├── reflect.py
│       │   └── embed.py
│       ├── cli/                  # Typer CLI (echo command)
│       │   ├── main.py           # app + 12 subcommands
│       │   ├── wizard.py         # echo init interactive flow
│       │   ├── migrate.py        # echo migrate-data
│       │   ├── serve.py          # echo serve (FastAPI + static UI)
│       │   └── view_reflections.py  # echo view-reflections
│       └── ui/
│           └── dist/             # Pre-built SvelteKit bundle (populated
│                                 #  by `cd ui && npm run build`)
├── api/                          # FastAPI backend (NOT in the package)
│   ├── main.py                   # app + CORS + router mount
│   ├── db.py                     # sqlite_utils singleton
│   ├── vec.py                    # LanceDB + embed_query
│   ├── llm.py                    # Anthropic native + OpenAI/OpenRouter routing
│   ├── observability.py          # Langfuse tracing wrapper (noop if no keys)
│   ├── routers/
│   │   ├── speak.py              # Echo Speaks ReAct loop (20 rounds, narrative-blind Phase 1)
│   │   ├── chat.py               # Ask Echo RAG demo
│   │   ├── insights.py           # Binge sessions + agency map
│   │   └── timeline.py           # Year/month/week aggregates
│   └── tools/                    # The 7-tool agent toolkit
│       ├── sql_tool.py           # run_sql (SELECT-only)
│       ├── python_tool.py        # execute_python (sandboxed via subprocess)
│       ├── pelt_tool.py          # run_pelt (changepoint on arbitrary table)
│       ├── clustering_tool.py    # run_clustering (k-means on lancedb)
│       ├── search_tool.py        # vector_search (lancedb cosine)
│       ├── youtube_tool.py       # youtube_lookup (quota-aware)
│       ├── web_search_tool.py    # web_search (5 calls/session, DDG)
│       └── compressors.py        # Per-tag observation compression (Layer 1)
├── ui/                           # SvelteKit frontend (separately built)
│   ├── src/
│   │   ├── routes/+page.svelte   # The Echo Speaks landing
│   │   └── lib/
│   │       ├── SpeakView.svelte  # Agent UI (rounds, findings, cost footer)
│   │       ├── CostFooter.svelte
│   │       ├── RoundPillStrip.svelte
│   │       └── TimelineCard.svelte
│   └── svelte.config.js
├── tests/                        # pytest suite
│   ├── conftest.py               # sets ECHO_DATA_DIR=repo_root for legacy integration tests
│   ├── test_compressors.py       # 40 unit tests for the Layer 1 compression registry
│   ├── test_trim_history_integration.py
│   ├── test_speak_response.py    # exception path + natural completion guards
│   ├── test_prompt_caching.py    # cache_control + streaming wiring
│   └── ...
└── (root configs)
    ├── Dockerfile / ui/Dockerfile / docker-compose.yml
    ├── .env.example              # canonical list of env vars
    ├── annotations.example.yaml  # template for private/annotations.yaml
    ├── metadata.yaml             # Datasette canned queries
    ├── requirements.txt          # legacy (pyproject.toml is the source of truth)
    └── README / SETUP / DATA / RUNBOOK / TODOS / CLAUDE / AGENTS / LICENSE
```

The split between `src/echo/` and `api/`:

- `src/echo/` is the **installable** package. `pip install -e .` puts the
  `echo` CLI on PATH and makes `from echo.config import ...` resolvable
  everywhere. The pipeline scripts live here so `echo run` works from
  anywhere on disk, not just inside a clone.
- `api/` is the **FastAPI server** for the SvelteKit UI. It's not in the
  package because it's invoked as `uvicorn api.main:app` (or by `echo serve`,
  which imports it). It depends on `echo.config` and `echo.data.paths` for
  data location, but otherwise stands alone.

---

## Tech choices and why

**Python 3.11+ for the pipeline + API.** `tomllib` is stdlib (no `tomli`
dep). `match` statements clean up the config loader. Type-hint syntax
(`X | None` instead of `Optional[X]`) reads better in EchoConfig.

**SQLite + sqlite-utils for primary storage.** One file (`echo.db`). No
server, no schema migrations, no daemon. The whole dataset (6K watches,
17K Spotify plays, 4K google searches, etc.) is < 100 MB. WAL mode handles
concurrent reads from the UI while the agent writes new rows.

**LanceDB for vectors.** Embedded (no separate process), file-based
(`~/.echo/lancedb/`), Apache Arrow under the hood. Drops in next to SQLite
with the same "delete the directory to reset" model. Chosen over Postgres +
pgvector (would require a server) and FAISS (in-memory only, no persistence
without extra code).

**ruptures for PELT.** Battle-tested, fast (sub-second on 200+ weeks of
multi-dimensional signals), clean API. `detect.py` z-score normalises each
dimension before fitting so the algorithm doesn't trip on different scales.

**Anthropic Claude (native API) as the primary LLM.** Two reasons:
1. Prompt caching with `cache_control: ephemeral` cuts per-round agent
   cost ~10x once the cache warms. We cache two blocks (the schema/rubric
   preamble and the phase-rules/tools instructions); both hit from round 2
   onwards.
2. The agent is a 20-round ReAct loop with structured `THOUGHT` / `ACTION` /
   `OBSERVATION` envelopes. Sonnet 4.6 / Opus 4.7 follow the schema more
   reliably than the OpenAI models we benchmarked.

OpenAI gpt-4o is the alternative for `reflect.py` (chapter narratives) and
agent fallback. OpenRouter routes both providers through one API for users
who prefer that.

**FastAPI for the backend.** Async streaming (Server-Sent Events for the
agent's per-round updates), automatic OpenAPI, type-checked request models.
The 4 routers (speak, chat, insights, timeline) each own ~200 lines.

**SvelteKit for the UI.** Compiles to small bundles, the runes API is
ergonomic, file-based routing fits a small app. The agent UI streams the
ReAct loop live (round pills, findings accordion, cost footer) via SSE.

**Typer for the CLI.** Lightweight wrapper around Click with type-hint
ergonomics. `echo init` walks five sections; `echo doctor` outputs a
diagnostic; each pipeline step is a thin subcommand calling
`echo.pipeline.<step>.run(config)`. ~250 lines of CLI code total.

**hatchling for the build.** Modern, fast, declarative (everything in
`pyproject.toml`). `force-include` ships the SvelteKit dist alongside the
Python package in one wheel.

**Datasette as a fallback browser.** When the agent feels overkill (or
when debugging the underlying data), `run.sh` launches Datasette with 17
canned queries from `metadata.yaml` for raw SQL exploration.

---

## Privacy architecture

The local-only constraint shapes several decisions:

| Concern | How we handle it |
|---|---|
| Personal data in source code | Every personal reference (school name, calendar labels, JEE / NDA / GSAC / McKinsey) was scrubbed via `git-filter-repo` before any public push. See `TODOS.md` for the Phase 2 scrub log. |
| Personal data in commits going forward | `private/annotations.yaml` lives in `~/.echo/private/` (gitignored). The repo ships `annotations.example.yaml` as a schema-only template. |
| LLM API exposure | The user picks the LLM provider; we never proxy. Each provider sees only what's in the prompt (chapter context for `reflect`, agent rounds for `speak`). No system-level prompt logging. |
| Data dir | `~/.echo/` by default (overridable via `$ECHO_DATA_DIR`). The user's `.env` lives there alongside `echo.db`, so secrets never touch the cloned repo. |
| Observability | Langfuse tracing is opt-in. If keys are absent, `_NoopLangfuse` silently no-ops every call. The instrumentation never sends raw data unless explicitly configured. |
| Container model | `docker compose` mounts the data dir read-only by default. `UNSAFE_PYTHON_SANDBOX=false` is forced in compose; opt-in lives only on trusted local machines. |

---

## Echo Speaks agent (the centerpiece)

`POST /api/speak` runs an autonomous ReAct loop:

- **20 rounds by default** (configurable in the UI; agent can also self-finish).
- **10-round narrative-blind Phase 1.** During Phase 1 the agent can't read the
  `reflections` LanceDB table (the GPT-4o narratives). This forces evidence-driven
  investigation before letting the agent lean on prior summaries. Phase 2 unlocks
  reflections.
- **7-tool toolkit:** `run_sql`, `execute_python` (sandboxed via subprocess with
  numpy/pandas/scipy/sklearn/statsmodels in the preamble), `vector_search`,
  `run_pelt`, `run_clustering`, `youtube_lookup` (quota-aware), `web_search`
  (5 calls/session, DuckDuckGo).
- **Per-round prompt caching.** Two `cache_control: ephemeral` checkpoints on
  the Anthropic native path. Block 1 (preamble: schema + rubric + stats) is
  stable across all rounds — hits from round 2. Block 2 (instructions: phase
  rules + tool list) is stable within each phase — hits from round 2, with one
  cache write at the Phase 1→2 boundary when the tool list expands. Reduces
  per-round cost ~10x once warm.
- **Layer 1 observation compression.** Older rounds get per-tool structured
  compression (`api/tools/compressors.py`) so the agent's context stays focused
  on recent rounds + compact summaries of earlier work. Real-world: a
  1892-char SQL observation compresses to ~165 chars (11x).
- **Per-finding evals.** ✓ Correct / ~ Partial / ✗ Wrong buttons on each
  finding POST to `/api/speak/score-finding` which logs `finding_N` scores
  to Langfuse for downstream LLM-as-judge eval.

---

## Pipeline contracts (idempotency)

Every step in `src/echo/pipeline/` declares its idempotency contract in its
top-of-file docstring. Summary:

| Script | Mechanism | What re-runs do |
|---|---|---|
| `ingest` | UNIQUE constraints on natural keys (video_id+watched_at, etc.) | New rows added; duplicates silently dropped. |
| `enrich` | Keyed by video_id; skips already-fetched | Only new video_ids hit the YouTube API. Quota safe. |
| `enrich_spotify` | Keyed by spotify_track_uri | Only new tracks hit Spotify search. |
| `detect` | DROP + recompute both output tables | Tune `--penalty` freely; no stale state. |
| `signals` | DROP + recompute watch_signals + spotify_signals | Tune constants near top of file; no stale state. |
| `reflect` | APPENDS new rows | Re-running adds more reflections; DELETE manually for a clean run. |
| `embed` | DROP + recreate each LanceDB table | Always fresh; the LanceDB dir is fully regenerable. |

This shape means `echo run` is always safe to re-run from scratch. Failure
mid-pipeline doesn't corrupt anything. Resume with `echo run --from <step>`.

---

## Open architectural questions

Tracked in [TODOS.md](./TODOS.md) for resolution in future sessions:

- **Spotify Phase 3b** — add `embed_spotify_tracks()` to `embed.py` so the
  agent can `vector_search` over Spotify tracks. Blocked on Phase 2 quota.
- **Echo Speaks Layer 2 / Layer 3** — heuristic scratchpad + Haiku
  summarization for >25-round runs. Deferred; Layer 1 alone may be sufficient.
- **LLM-as-judge eval batch** — automate evaluation against the 20+
  human-annotated traces collected via the score buttons.
- **PyPI publication** — `pip install echo-archaeology` once the V1 install
  flow is stable on more than one machine.
- **SvelteKit `adapter-static`** — the UI build pipeline currently uses
  `adapter-auto`; switching to `adapter-static` would let `echo serve` ship
  fully prerendered HTML/CSS/JS instead of requiring an SSR runtime.
