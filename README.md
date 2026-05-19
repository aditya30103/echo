# Echo

**Your past, heard back.**

Echo turns your Google Takeout (YouTube watches, searches, calendar) and Spotify
Extended Streaming History into a queryable local database, then runs an autonomous
Claude-powered agent over it. The agent finds chapters in your life from the
changepoints in your viewing patterns, writes narrative reflections of each one,
and answers free-form questions like "what was I anxious about in early 2024" or
"show me my deepest binge sessions" — with evidence trails back to the underlying rows.

It runs entirely on your machine.

---

## Privacy

Echo is a local tool. Your data never leaves your computer except for the LLM
API calls **you** configure (Anthropic, OpenAI, or OpenRouter) — and those
calls hit only the providers you set keys for. No telemetry, no analytics, no
hosted version, no upload, no sync. You own:

- the SQLite database (`~/.echo/echo.db`)
- the vector index (`~/.echo/lancedb/`)
- the reflections written by GPT-4o (in `echo.db`)
- the embeddings (cached locally)
- your API keys (in `~/.echo/.env`, never committed)

When you stop using Echo, you delete `~/.echo/` and that's the end of it.

---

## What you'll need

- **Python 3.11+**
- **Node.js 20+** (only if you want the SvelteKit UI; the CLI works without it)
- **~5 GB disk** for the database, vector index, and (large) Takeout zip
- **A Google Takeout export** of your YouTube history + My Activity + Calendar:
  download at <https://takeout.google.com>
- **(Optional) A Spotify Extended Streaming History export**: request at
  <https://spotify.com/account/privacy> — takes Spotify ~30 days to ship
- **(Optional) API keys**:
  - Anthropic Claude — for the autonomous Echo Speaks agent (best results)
  - OpenAI or OpenRouter — for chapter reflections + embeddings (~$0.15 for a
    full reflection pass on 16 chapters; ~$0.01 for embeddings)
  - YouTube Data API — for video metadata enrichment (free, 10K quota/day)
  - Spotify Web API — for track metadata (free, Client Credentials flow)

If you don't have API keys yet, run `echo init` first — it links to every
provider's dashboard and walks you through the setup.

---

## Quick start

```bash
git clone https://github.com/<you>/echo.git
cd echo
pip install -e .

echo init      # 5-section interactive wizard; writes ~/.echo/config.toml + .env
echo run       # ingest -> enrich -> detect -> signals -> reflect -> embed
echo serve     # open http://localhost:8000  (or: docker compose up)
```

Full walkthrough in [SETUP.md](./SETUP.md).

---

## CLI reference

`echo --help` lists everything. Quick map:

| Command | What it does |
|---|---|
| `echo init` | First-run setup wizard. Pass `--non-interactive` for scripted/CI use. |
| `echo run [--from STEP]` | Full pipeline (ingest → enrich → detect → signals → reflect → embed). |
| `echo doctor` | Sanity-check the install: paths, configured zips, API keys, DB schema. |
| `echo ingest` | Just load Takeout/Spotify zips into `echo.db`. |
| `echo enrich [--key K]` | YouTube Data API enrichment. |
| `echo enrich-spotify [--dry-run]` | Spotify Web API enrichment. |
| `echo detect [--penalty N] [--plot]` | PELT changepoint detection. |
| `echo signals` | Engagement scoring (sessions, autoplay, rewatch, search-driven). |
| `echo reflect [--dry-run] [--chapter N] [--autobiography]` | GPT-4o reflections. Always run `--dry-run` first. |
| `echo embed [--dry-run] [--table T]` | LanceDB vector embedding. |
| `echo view-reflections` | Render chapter reflections to an HTML page. |
| `echo serve [--host] [--port]` | Start FastAPI + bundled UI on one port. |
| `echo migrate-data --from PATH` | One-time: move pre-packaging state into `~/.echo/`. |

---

## Status

| | |
|---|---|
| Pipeline (ingest → embed) | ✅ shipped |
| Echo Speaks agent (20-round ReAct, 7-tool toolkit, two-block prompt caching) | ✅ shipped |
| SvelteKit UI (Echo Speaks landing, Binge Sessions, Agency Map, Ask Echo) | ✅ shipped |
| Spotify Phase 1 (ingest) + Phase 3 (signals) | ✅ shipped |
| Spotify Phase 2 (enrich_spotify track metadata) | ⏳ quota-blocked; works when unblocked |
| Spotify Phase 3b (embed_spotify_tracks → LanceDB) | ⏳ blocked by Phase 2 |
| Packaged CLI (`echo` command, `pip install -e .`) | ✅ shipped (this branch) |
| PyPI release (`pip install echo-archaeology`) | 🔜 V2 |

See [TODOS.md](./TODOS.md) for the deferred-work list with context.

---

## Documentation

| Doc | Read it for |
|---|---|
| [SETUP.md](./SETUP.md) | First-time install + run, step by step |
| [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) | High-level design, module map, tech choices |
| [docs/DATA.md](./docs/DATA.md) | Every table, every column, how it's computed |
| [docs/RUNBOOK.md](./docs/RUNBOOK.md) | Operating the pipeline, idempotency contracts, debugging |
| [docs/DESIGN.md](./docs/DESIGN.md) | Visual design system — two-temperature principle, color tokens, typography, component patterns |
| [CLAUDE.md](./CLAUDE.md) / [AGENTS.md](./AGENTS.md) | Conventions for AI assistants working on the codebase |
| [TODOS.md](./TODOS.md) | Deferred work + ship-blocker tracking |
| [annotations.example.yaml](./annotations.example.yaml) | Template for the per-user life-context file |

---

## Tech stack

Python 3.11 (FastAPI + sqlite-utils + LanceDB + ruptures + scikit-learn) +
SvelteKit 2 + Anthropic Claude + OpenAI gpt-4o + Datasette (for raw DB browsing).
Built and packaged with hatchling. MIT licensed.

---

## License

[MIT](./LICENSE) © 2026 Aditya Arya.
