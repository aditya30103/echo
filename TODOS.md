# Echo TODOS

Active deferred work. Each item has enough context to pick up without re-reading
the session that produced it. Completed work is archived at the bottom.

---

## TODO: Integration tests against a fixture Takeout zip

**What:** Create `tests/fixtures/sample-takeout.zip` (hand-crafted, few KB,
~10 watches + 5 searches + 3 calendar events). Add one smoke test per
pipeline step that runs that step against the fixture and asserts row counts
in the resulting tables. Plus `typer.testing.CliRunner` tests for the CLI
init wizard (via piped input or via the extracted `run_wizard` function).

**Why:** Current pytest passes 105 tests but only `test_pelt_happy_path` /
`test_clustering_happy_path` actually exercise the pipeline against real data.
The right shape for a public OSS project is per-step integration tests with a
deterministic fixture that ships in the repo without leaking personal data.

**Approach:**
1. Build a synthetic Takeout zip: tiny JSON files mimicking the Google export
   structure with ~10 fake watches across 4 weeks.
2. New `tests/test_pipeline_integration.py` with one `tmp_path`-based test per step:
   ```python
   def test_ingest_against_fixture(tmp_path):
       cfg = EchoConfig(data_dir=tmp_path,
                        takeout=TakeoutPaths(youtube_zip=FIXTURE_YT_ZIP))
       ingest.run(cfg)
       assert sqlite_utils.Database(cfg.db_path)["watches"].count == 10
   ```
3. Retire the `ECHO_DATA_DIR=repo_root` shim in conftest.py.

**Blocked by:** Nothing — just session time (~2h).

---

## TODO: GitHub Action smoke test on a fresh container

**What:** Workflow on every PR: clone → `pip install -e .` → `echo init
--non-interactive --youtube-zip tests/fixtures/sample-takeout.zip` → `echo run`
→ assert expected tables. Fails the PR if any step exits non-zero.

**Why:** Catches "works on my machine" regressions. Proves the packaged install
works on a clean machine with no existing `.env` or `~/.echo/`.

**Blocked by:** Integration tests + fixture (item above).

---

## TODO: Echo Speaks context mgmt — Layers 2 & 3

**What:** Layer 1 (per-tool structured compression via `api/tools/compressors.py`)
shipped 2026-05-15. Layer 2 (heuristic finding scratchpad) and Layer 3 (Haiku
summarization for runs > 25 rounds) remain deferred.

**Why deferred:** Layer 1 expanded temporal coverage dramatically (A/B confirmed).
Commission Layer 2/3 only if real-world findings still feel fragmentary after a few
weeks of use. Each gets its own `/plan-eng-review` when commissioned.

**Blocked by:** Real-world signal from Layer 1 in production.

---

## TODO: Spotify Phase 2 — enrich_spotify.py (duration_ms + explicit)

**What:** Run `echo enrich-spotify` once a new Spotify Developer app is available.
~4,322 tracks pending at 1 req/s → ~72 min. Writes `duration_ms`, `explicit`,
`uri_verified` to `spotify_tracks`.

**Why deferred:** Spotify account rate-limited for new app creation (as of 2026-05-14).

**When unblocked:**
1. Create new Spotify app at developer.spotify.com/dashboard
2. Add `SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET` to `.env`
3. `echo enrich-spotify --dry-run` — confirm pending count
4. `echo enrich-spotify` — check progress every 5%

---

## TODO: Spotify-genres follow-up (deferred from rework)

**What:** If Last.fm tags are too noisy for cross-modal queries, add a step that
hits Spotify `/artists/{id}` for the curated genre taxonomy. Depends on capturing
`artists[0].uri` during `enrich-spotify` (2-line change).

**Trigger:** Run a `/qa` pass against cross-modal mood queries after a week of
`enrich-music-meta` in production. If recall is good, skip permanently.

---

## TODO: Per-play tag materialization on spotify_signals

**What:** Add `primary_tag_at_play` and `primary_genre_at_play` to `spotify_signals`.
Materializes the JOIN `spotify_signals → spotify_tracks` at signal-computation time.

**Why:** SQL mood filters currently need a 3-way join. Defer until mood filters
become a hot path in agent traces.

---

## TODO: DeepSeek / Ollama routing in api/llm.py

**What:** Add DeepSeek (cloud) or Ollama (local) slug to `api/llm.py` via
`OPENROUTER_BASE_URL` or a new `OLLAMA_BASE_URL`. Same interface as OpenRouter path.

**Why:** Cheap local inference for development and offline use.
**Cons:** Quality gap on multi-step ReAct loops. Low urgency.

---

## TODO: Validate finding_index in /api/speak/score-finding

**What:** Bounds-check `finding_index` before posting to Langfuse. Currently
any index creates a spurious score with no error. Low priority while the only
caller is the frontend (which can't generate out-of-range indexes in practice).

---

## TODO: Handle score-finding network errors in SpeakView.svelte

**What:** When `POST /api/speak/score-finding` returns non-200, show an inline
error instead of the optimistic "submitted" state. Low priority while Langfuse
is always-available or noop.

---

## TODO: LAION-CLAP audio embeddings

**What:** Replace text-embedding-3-small for `spotify_tracks` with joint
audio↔text via `laion/clap-htsat-unfused`. Embed Spotify 30-second previews
into the same vector space as text queries.

**Why:** Coolest cross-modal path (no API; the audio itself participates).
Week-scale work; captured so it isn't lost.

---

## TODO: LLM-as-judge eval batch after 20+ annotated traces

**What:** After 20+ human-annotated findings exist in Langfuse, run a batch
LLM-as-judge pass: submit `(claim + evidence + source_tag)` to GPT-4o, compare
to human score, flag systematic biases by source_tag.

**Blocked by:** Needs 20+ human-annotated sessions.

---

## Completed

| Session | What shipped |
|---|---|
| 2026-05-19 | Spotify/YouTube agent parity — spotify_tracks in search tool, speak rubric/schema/Phase 1, chat retrieval; fix llm_chat unpack bug in Ask Echo; CI ANSI test fix |
| 2026-05-19 | OSS release prep — BLOCKING personal strings removed, /docs/ move, INSTALL.md, onboarding clarity, .gitignore audit, CLAUDE.md/TODOS.md cleanup |
| 2026-05-17 | SvelteKit adapter-static build — dist/ committed to git; echo serve serves full UI |
| 2026-05-18 | Music meta enrichment (Tier 1+2 Last.fm), 5th LanceDB table (spotify_tracks), design system lock, soul transplant, design audit (78→84), design overhaul FINDING-011–014 |
| 2026-05-16–17 | packaging-v1 merged: installable CLI, EchoConfig, all 8 pipeline scripts migrated, Typer CLI, api/ migration, echo serve, echo migrate-data, README/SETUP/ARCHITECTURE docs |
| 2026-05-15 | Layer 0+1 context management, A/B test confirmation |
| 2026-05-16 | History rewrite (scrubbed personal annotations from master commits) |
