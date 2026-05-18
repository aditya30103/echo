# Echo TODOS

Deferred work captured during engineering reviews. Each item includes enough context to
pick up without re-reading the session that produced it.

---

## Design Overhaul — deferred from soul transplant session (2026-05-18) ✓ COMPLETE

Soul transplant shipped: amber palette, Lora/Geist Mono dual typeface, CSS token system,
touch targets, all component color passes. Design score C → B, AI Slop C → A.

All four findings shipped in the design overhaul session (2026-05-18). See git history.

### FINDING-011 — Model selector behind Advanced toggle ✓ SHIPPED

**What:** The Auto / Claude / GPT-4o model selector is always visible in the query
controls bar. It's an advanced control that most users will never touch after their
first session. Hide it behind an "Advanced ›" disclosure toggle.

**Why:** The query card's primary job is to invite investigation, not surface model
selection. The selector adds cognitive load on first load and competes with the
textarea + Investigate button for attention.

**Approach:** Wrap the `.model-toggle` and `.rounds-label` in a collapsed `<details>`
or a toggle state variable. Show only a dim "Advanced ›" label when closed. Expand
inline when clicked. Persist collapsed state in `localStorage` so power users don't
have to re-open every session.

**Source:** Design identity doc (2026-05-18), explicitly deferred.

---

### FINDING-012 — Ask Echo controls layout restructure ✓ SHIPPED

**What:** The Ask Echo tab (RAG chat) has a control layout that doesn't match the
visual language established by the soul transplant. The input area and submit controls
need the same card-in-void treatment the Echo Speaks card got.

**Why:** Consistency across tabs. Echo Speaks looks finished; Ask Echo looks like it
wasn't in scope (it wasn't — correctly deferred).

**Approach:** Apply the same `.query-panel` card structure (surface-0 bg, border,
padding, Lora textarea) to the Ask Echo input. Confirm touch targets on submit. Run
a design review pass after.

**Source:** Design identity doc (2026-05-18), explicitly deferred.

---

### FINDING-013 — Mobile layout ✓ SHIPPED

**What:** No mobile-specific layout work was done in the soul transplant session beyond
touch targets (44px min-height on all interactive elements). The Agency Map table and
Binge Sessions card list likely overflow or compress poorly on narrow viewports.

**Why:** Echo's public debut means friends will try it on mobile. The Agency Map table
is the highest risk — horizontal bar charts and wide tables are known overflow candidates.

**Approach:** Add a `@media (max-width: 640px)` pass. Agency Map: stack or horizontally
scroll the table. Binge Sessions: verify card layout collapses to single-column cleanly.
Nav tabs: confirm they don't wrap awkwardly. Run a design review at 375px viewport.

**Source:** Design identity doc (2026-05-18), explicitly deferred.

---

### FINDING-014 — Animation and motion ✓ SHIPPED

**What:** No transitions exist on view switches, finding reveals, or the round trace
expanding/collapsing. The UI snaps between states with no motion.

**Why:** The soul transplant established a strong static identity. Motion is the next
layer — used conservatively, it reinforces the "slow reveal from a drawer" metaphor.
Used carelessly, it makes the product feel like a SaaS dashboard.

**Approach:** Two candidates worth doing, nothing else:
1. `finding-item` entrance — a subtle fade-in (opacity 0→1, 150ms ease) as each
   finding arrives during streaming. The findings appearing one by one already has
   narrative weight; a fade amplifies it.
2. View transition — a 100ms opacity cross-fade when switching nav tabs.
Avoid slide animations, bounce, or anything that draws attention to itself.

**Source:** Design identity doc (2026-05-18), explicitly deferred.

---

## Design System — ✓ SHIPPED (2026-05-18)

Formal design system locked down after the soul transplant session.

- **`DESIGN.md`** at repo root — canonical design reference. Philosophy, color tokens,
  typography rules, component patterns, two-temperature principle, what never changes.
  Authoritative for all future contributors.
- **`ui/src/lib/SourceChip.svelte`** — source provenance chips. Encodes the
  `--signal-cold-dim` border rule in code. Used in Echo Speaks findings and round
  observations. All future source tags must use this component.
- **`ui/src/lib/SessionCard.svelte`** — binge session card. Encodes Lora depth number,
  accent bar fill, and badge color semantics (searched=cold, autoplay=muted,
  rewatch=amber) in one place.

Both components extracted from inline markup and CSS; SpeakView and +page.svelte updated.

---

## Design Audit — /design-review run (2026-05-18)

**Status:** 3/4 findings fixed. FINDING-004 deferred (polish-level).

FINDING-001, -002, -003 shipped in commits `80c6765`, `f88f9db`, `62f6a43`.
Design score: B (78) → B+ (84). Full audit report at
`~/.gstack/projects/Echo/designs/design-audit-20260518/design-audit-localhost.md`.

### FINDING-004 — Agency Map section header contrast (deferred, polish)

**What:** Agency section headers use `--text-muted` on `--surface-0`. Contrast
may be borderline for WCAG AA on the label text above each agency bar group.

**Why deferred:** These are section dividers, not primary reading content. The
risk is low and fixing it may require a new semantic token between `--text-muted`
and `--text-secondary`. Not worth doing in isolation.

**Fix when ready:** Audit computed contrast, and if below 4.5:1, move section
labels to `--text-secondary`. Takes 5 minutes once decided.

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

## ~~TODO: Spotify Phase 3b — embed spotify_tracks into lancedb~~ — REPLACED

Superseded 2026-05-18 by the Spotify Rework design (`~/.gstack/projects/Echo/Aditya Arya-master-design-spotify-rework-20260517-231729.md`). The original Phase 3b assumed `"track_name | artist_name"` strings as the embedding text. The rework adds Last.fm mood/genre tags as the actual dimension that makes cross-modal queries useful, and lands the embedding via `enrich-music-meta` + `embed.py` extension across phases A-F.

Shipped: `enrich_music_meta.py` with Tier 1 + Tier 2, `spotify_tracks` as the 5th lancedb table, fail-soft on missing key, batch-flush resilience.

---

## TODO: Spotify-genres follow-up (deferred from rework)

**What:** If the Last.fm tag vocabulary turns out too noisy for cross-modal queries in practice, add a follow-up step that hits Spotify `/artists/{id}` for the curated genre taxonomy. Depends on capturing `artists[0].uri` from Spotify search responses during `enrich-spotify` (a 2-line change).

**Why:** Skipped from v1 because it reintroduces Spotify quota dependency and the artist-URI sourcing problem that the Last.fm-only path was designed to avoid. Add only if real agent queries show Last.fm noise harming recall.

**Trigger:** Run a `/qa` pass against cross-modal mood queries after `enrich-music-meta` has been in place for ~1 week. If recall is good, skip permanently.

---

## TODO: Per-play tag materialization on spotify_signals

**What:** Add `primary_tag_at_play` and `primary_genre_at_play` columns to `spotify_signals` (or to a small per-play view). Materializes the JOIN `spotify_signals -> spotify_tracks` at signal-computation time.

**Why:** SQL-driven mood filters ("show me sessions where I was listening to melancholy music") currently require a 3-way join. Materializing the dominant tag per-play makes those queries one table read. Defer until SQL-driven mood filters become a hot path in agent traces.

---

## TODO: LAION-CLAP audio embeddings

**What:** Replace text-embedding-3-small for `spotify_tracks` with joint audio↔text via `laion/clap-htsat-unfused`. Embed Spotify 30-second preview clips into the same vector space as text queries.

**Why:** Coolest cross-modal play (no API at all; the audio itself participates). Depends on Spotify `/audio-preview` URL availability, which is rights-dependent and covers ~40-60% of tracks. Week-scale work; deferred to a future design session entirely. Captured here so it's not lost.

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
