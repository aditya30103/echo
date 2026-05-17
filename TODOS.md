# Echo TODOS

Deferred work captured during engineering reviews. Each item includes enough context to
pick up without re-reading the session that produced it.

---

## NOTE: Packaging session 1 + 2 — completion summary

**Status:** `packaging-v1` branch is feature-complete for the packaged-CLI
release. ~22 commits ahead of `master`. End-state:

What shipped:
- **Package skeleton** (`src/echo/{pipeline,cli,config,data,ui}/`) + `pyproject.toml`
  (hatchling, name `echo-archaeology`, all deps + dev extras, force-include for
  the bundled UI directory, console script `echo`).
- **EchoConfig** dataclass + TOML/.env loader. Single source of truth for
  paths, API keys, enrichment toggles, LLM provider, observability.
- **All 8 pipeline scripts migrated** to `src/echo/pipeline/*.py` (and
  `viewer.py` → `src/echo/cli/view_reflections.py`). Each exposes
  `run(config: EchoConfig) -> None`; the legacy direct `python -m
  echo.pipeline.<name>` invocation continues to work via thin argparse wrappers.
- **Typer CLI** with 12 subcommands (`init`, `run`, `doctor`, the 7 pipeline
  steps, `view-reflections`, `serve`, `migrate-data`). `--non-interactive` mode
  on `init` for CI / scripted setup.
- **api/ migration**: 9 files swapped from `Path(__file__).parent.parent /
  "echo.db"` style hardcoded paths + `from embed_common import` + sys.path
  hacks to `from echo.config / echo.data.paths import ...`. Closed the eng
  review's CRITICAL finding.
- **embed_common.py shim deleted** (zero remaining callers after api/ migrate).
- **Docker reads echo via pyproject.toml + ECHO_DATA_DIR mount.** docker-compose
  now mounts `${ECHO_DATA_DIR:-./}:/data:ro` and the api container reads
  `ECHO_DATA_DIR=/data` internally.
- **echo migrate-data** for the one-time move of pre-packaging state into
  `~/.echo/`. Preserves the dev's reflections + lancedb (saves 10K YouTube
  quota + ~$5 GPT-4o spend).
- **echo serve** mounts FastAPI + bundled SvelteKit UI on one port (8000) so
  friends without Docker can use the full app.
- **Docs trio** (README, SETUP, ARCHITECTURE) written around the packaged CLI.
- **requirements.txt retired** in favor of pyproject.toml; RUNBOOK + CLAUDE
  references updated.

Pytest baseline preserved across all 22 commits: **105 pass + 4 known-flaky**.

What's queued for the NEXT session (in priority order):
1. Fixture-based integration tests (see "Integration tests" entry below).
2. GitHub Action smoke test (clone -> `pip install -e .` -> `echo init
   --non-interactive` -> `echo run` against the fixture).
3. SvelteKit `adapter-static` swap so `echo serve` ships the UI prebuilt
   (currently the wheel ships an empty `src/echo/ui/dist/`).
4. Merge `packaging-v1` -> `master` after items 1-3.
5. Optional V2: PyPI publish via trusted-publishing GitHub Action.

**Design doc:** `~/.gstack/projects/Echo/Aditya Arya-master-design-packaging-20260516.md`.

---

## TODO: Integration tests against a fixture Takeout zip

**What:** Create `tests/fixtures/sample-takeout.zip` (hand-crafted, few KB,
~10 watches + 5 searches + 3 calendar events). Add one smoke test per
pipeline step that runs that step against the fixture and asserts row counts
in the resulting tables. Plus `typer.testing.CliRunner` tests for the CLI
init wizard (via piped input or via the extracted `run_wizard` function).

**Why:** Current pytest passes 105 tests but only `test_pelt_happy_path` /
`test_clustering_happy_path` actually exercise the pipeline against real data
(via the conftest.py `ECHO_DATA_DIR=repo_root` shim). After packaging, the
right shape is per-step integration tests with a deterministic fixture
that can ship in the repo without leaking personal data.

**Approach:**
1. Build a synthetic Takeout zip: tiny JSON files mimicking the Google export
   structure (`Takeout/My Activity/YouTube/MyActivity.json`,
   `Takeout/YouTube and YouTube Music/history/watch-history.json`, etc.) with
   10 fake watches across 4 weeks.
2. New test module `tests/test_pipeline_integration.py` with one `tmp_path`-based
   test per step. Pattern:
   ```python
   def test_ingest_against_fixture(tmp_path):
       cfg = EchoConfig(data_dir=tmp_path,
                        takeout=TakeoutPaths(youtube_zip=FIXTURE_YT_ZIP))
       ingest.run(cfg)
       db = sqlite_utils.Database(cfg.db_path)
       assert db["watches"].count == 10
   ```
3. Retire the `ECHO_DATA_DIR=repo_root` shim in conftest.py once
   `test_pelt_happy_path` / `test_clustering_happy_path` move to fixtures too.

**Pros:** Real CI gate. Catches packaging regressions before merge.
**Cons:** ~2 hours of fixture-building + test-writing.
**Blocked by:** Nothing; just session time.

---

## TODO: GitHub Action smoke test on a fresh container

**What:** A workflow that on every PR (and merge to master) runs:
clone -> `pip install -e .` -> `echo init --non-interactive
--youtube-zip tests/fixtures/sample-takeout.zip` -> `echo run` -> assert
echo.db has the expected tables. Fails the PR if any step exits non-zero.

**Why:** Proves the packaged install works on a clean machine (no dev's
existing `.env` / `~/.echo/` to mask issues). Catches "works on my machine"
regressions immediately.

**Blocked by:** Item above (integration tests + fixture).

---

## TODO: SvelteKit adapter-static for `echo serve` UI bundling

**What:** Install `@sveltejs/adapter-static` in `ui/`, update
`svelte.config.js` to use it with `fallback: 'index.html'` for SPA routing,
run `npm run build` (outputs to `ui/build/`), copy to `src/echo/ui/dist/`,
verify `echo serve` returns the rendered HTML.

**Why:** Currently `echo serve` prints a "UI not bundled" message because
`src/echo/ui/dist/` only contains the `.gitkeep` placeholder. The wheel's
`force-include` is already wired (pyproject.toml); the build step itself is
the remaining piece.

**Blocked by:** Nothing; just session time + verifying the static build
prerenders correctly with the existing routes.

---

## NOTE: Phase 2 history rewrite — completion summary

**Status:** Executed 2026-05-16 via 4 git-filter-repo passes on master only.
All 58 commit SHAs changed. Backup branch `backup-before-history-rewrite`
preserves the pre-rewrite state at original SHA `00ea0bd`. External `.git`
snapshot at `../Echo-git-backup-20260516/` (2.6MB) as second-layer safety.

**What was scrubbed from master history:**
- `annotations.yaml` (full biographical timeline) — file removed entirely
- `metadata.yaml` personal phrases (year/channel/calendar refs from initial commit)
- DATA.md transaction date range and count
- Phase 1 commit message and TODOS.md content that inadvertently re-leaked the
  same biography while documenting the cleanup

**Intentionally kept (per user decision, on-brand for explicitly-Indian-student project):**
- `JEE Advanced` example queries in `api/tools/__init__.py` and `ui/.../+page.svelte`
- Residual `[McK]` calendar label references in older commit content (McK is just
  a calendar label name; McKinsey appears only as disambiguation)
- "Indian student, ages 13-23" framing in README/CLAUDE.md (load-bearing context)

**Before pushing to a public GitHub remote:**
1. Verify `git remote -v` shows the intended public remote (currently no remote configured)
2. Push ONLY master: `git push -u origin master` (do NOT push backup branch or worktree branch)
3. Delete `backup-before-history-rewrite` after first successful clone-and-verify by a
   friend (or keep it forever; it never reaches the public repo unless explicitly pushed)
4. Optionally `git gc --prune=now --aggressive` to remove unreachable objects locally
   (only relevant after deleting the backup branch)

**Source:** Step 0 of the release-prep cleanup design at
`~/.gstack/projects/Echo/Aditya Arya-master-design-release-prep-20260516.md`.

---

## TODO: Echo Speaks context mgmt — Layers 2 & 3 (deferred design reviews)

**What:** Layer 0 (housekeeping) and Layer 1 (per-tool structured compression in
`api/tools/compressors.py`) shipped 2026-05-15. Layers 2 (heuristic scratchpad)
and 3 (Haiku-driven summarization for runs > 25 rounds) remain deferred.

**Why deferred:** Layer 1 produced a ~22% cost increase but expanded temporal
coverage dramatically (A/B test confirmed). Production use of Layer 1 alone may
be sufficient; commission Layer 2/3 design reviews only if real-world findings
still feel fragmentary or shallow over a few weeks of use.

**Approach when commissioned:** Each gets its own `/plan-eng-review`. Layer 2
keeps a structured scratchpad of confirmed findings the agent maintains across
rounds. Layer 3 fires Haiku summarization on history older than N rounds.

**Blocked by:** Real-world signal. Live with Layer 1 first.

---

## TODO: DeepSeek / Ollama routing in api/llm.py

**What:** Add DeepSeek (cloud) or Ollama (local) model slug to `api/llm.py`,
pointing at the local Ollama server via `OPENROUTER_BASE_URL` (or a new
`OLLAMA_BASE_URL`). Same interface as the current OpenRouter path.

**Why:** Cheap local inference for development iteration and offline use.
Useful for cost-bounded experimentation that doesn't need Claude / GPT-4o
quality.

**Cons:** Quality gap on multi-step ReAct loops. Local models often loop
or fail to follow the structured Action/Thought format.

**Blocked by:** Nothing technical. Low urgency.

---

## TODO: Validate finding_index in /api/speak/score-finding

**What:** Check that `finding_index` is in range `[0, len(findings) - 1]` for the given trace.

**Why:** `score_finding` currently posts any `finding_index` to Langfuse without bounds
checking. An out-of-bounds index (e.g., `finding_999` on a 3-finding trace) creates a
spurious Langfuse score with no error to the caller.

**Pros:** Prevents silent data corruption in the Langfuse eval dashboard. Becomes important
if any external caller or script sends requests.

**Cons:** Requires server-side state: storing finding count per `trace_id`. Adds complexity.

**Context:** Currently single caller (frontend), which generates the index directly from the
findings array — will never be out-of-bounds in practice. Low priority until external callers
exist or spurious scores appear in the Langfuse dashboard.

**Approach:** Store `{trace_id: finding_count}` in a module-level dict in `speak.py` (populated
at `trace.finish()` time). Or add `GET /api/speak/trace/{trace_id}/findings` for server-side
count lookup.

**Blocked by:** Not pressing. Revisit after open-source release if external callers emerge.

---

## TODO: Handle score-finding network errors in SpeakView.svelte

**What:** When `POST /api/speak/score-finding` returns non-200, show a brief inline error
next to the score button instead of the optimistic "submitted" state.

**Why:** The button currently shows "submitted" regardless of response status. If Langfuse is
down, the eval score is silently lost — defeating the eval collection purpose.

**Pros:** Makes failures visible. Allows user to retry.

**Cons:** Minor UI complexity (new 'error' state in `findingScores`).

**Context:** Only matters when Langfuse is configured as a remote instance and experiences
downtime. Local noop Langfuse (no key configured) silently drops scores by design — this
is expected behavior, not an error.

**Approach:** Check `response.ok` after fetch. Add `'error'` state alongside `'idle'` and
`'submitted'` in the `findingScores` record. Show a red `!` icon with tooltip "Score failed
— try again."

**Blocked by:** Low priority while Langfuse is noop or always-available.

---

## TODO: Spotify Phase 2 — enrich_spotify.py (duration_ms + explicit)

**What:** Run `python enrich_spotify.py` once a new Spotify Developer app is available.
~4,322 tracks pending at 1 req/s → ~72 min. Writes `duration_ms`, `explicit`, `uri_verified`
to `spotify_tracks` table.

**Why:** Blocked by Spotify app quota: original app was deleted, replacement creation was
rate-limited for 24 hours. Safe to run any time after a new app is created at
developer.spotify.com/dashboard (Client Credentials flow, no user login needed).

**Note:** `reason_end = 'trackdone'` already provides a superior completion signal —
Phase 3 behavioral signals are fully functional without this. `duration_ms` adds completion
ratio computation and enables the Spotify lancedb embedding (Phase 3b below).

**When unblocked:**
1. Create new Spotify app at developer.spotify.com/dashboard
2. Add `SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET` to `.env`
3. `python enrich_spotify.py --dry-run` — confirm 4,322 pending
4. `python enrich_spotify.py` — ~72 min, check progress every 5%

**Blocked by:** Spotify account: "created too many apps recently, try again in 24h" (as of 2026-05-14).

---

## TODO: Spotify Phase 3b — embed spotify_tracks into lancedb

**What:** Add `embed_spotify_tracks()` to `embed.py`. Embed `"track_name | artist_name"` strings
from `spotify_tracks` into a new lancedb `spotify_tracks` table. Wire into agent `vector_search`
dispatch in `api/tools/search.py`.

**Why:** Lets the agent answer "find tracks similar to X" or "what was I listening to around the
same time as [YouTube topic]?" via semantic search — right now Spotify is SQL-only.

**Blocked by:** Phase 2 (enrich_spotify.py) must complete first so `spotify_tracks` has populated
`track_name` and `artist_name` rows to embed.

---

## TODO: LLM-as-judge eval batch after 20+ annotated traces

**What:** After 20+ human-annotated findings exist in Langfuse, run a batch LLM-as-judge pass.
For each finding, submit `(claim + evidence + source_tag)` to GPT-4o and ask: "Is this claim
well-supported by the evidence? Score 0–1 with justification." Compare to human score.

**Why:** Per-finding human evals (via the Sprint 5 score buttons) build the ground truth dataset.
LLM-as-judge can then scale to all new sessions automatically, surfacing systematic gaps (e.g.,
SEMANTIC-RAW findings always overconfident).

**Pros:** Scales eval coverage beyond what manual annotation can sustain.

**Cons:** Requires OpenAI API credits. Outputs are probabilistic — treat as signal, not ground truth.

**Context:** Sprint 5 builds the human eval collection mechanism. This TODO activates once the
dataset exists. Design doc (Task 7) already anticipated this.

**Approach:** New script `eval_findings.py`. Fetches Langfuse traces where `finding_N` scores
exist, runs GPT-4o judge prompt per finding, logs human/LLM score correlation, flags systematic
biases by `source_tag`.

**Blocked by:** Needs 20+ human-annotated sessions. Estimate: 3–4 hrs once dataset exists.
