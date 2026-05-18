# Echo setup walkthrough

Step-by-step install for someone who has never run Echo before. ~15 minutes of
hands-on time + however long Google takes to mail you your Takeout (usually a
few hours). API calls run in the background — total wall-clock can stretch to
a few hours if you opt in to GPT-4o reflections, but you can step away.

If you just want the 30-second version, see [README.md § Quick start](./README.md#quick-start).

---

## 0. Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | 3.11 / 3.12 / 3.13 all tested. |
| Node.js 20+ | Only if you want the SvelteKit UI. The CLI alone works fine without it. |
| Docker (optional) | If you'd rather run the API + UI in containers instead of locally. |
| ~5 GB free disk | Takeout zips + `echo.db` + LanceDB index. The Takeout zip dominates. |
| A Google account with YouTube history | The whole point of Echo. |
| A Spotify account (optional) | For cross-modal queries. |

API keys (you'll be prompted for them by `echo init` in Step 4; you can also add
them later by editing `~/.echo/.env`):

| Key | Free? | Used for |
|---|---|---|
| Anthropic Claude | Yes, pay-as-you-go | Echo Speaks agent (recommended). |
| OpenAI | Yes, pay-as-you-go | GPT-4o reflections, embeddings, agent fallback. |
| OpenRouter | Yes, pay-as-you-go | Alternative path for OpenAI calls. |
| YouTube Data API | Yes, free 10K units/day | Video metadata enrichment (title, category, duration). |
| Spotify Developer | Yes, free | Track metadata enrichment (post-Nov-2024 apps lose audio features). |

You don't need all of them. Echo runs without any keys — you just get a smaller
pipeline (no enrichment, no reflections, no agent). Start with just YouTube and
one LLM provider; add the rest later.

---

## 1. Get your Takeout

1. Go to <https://takeout.google.com>.
2. **Deselect all**, then select:
   - **YouTube and YouTube Music** → History (this gives you watch + search history + Watch Later)
   - **My Activity** → at least YouTube, Search, Discover. Pay too if you use Google Pay.
   - **Calendar** (for chapter context).
3. Click **Next step**, then **Create export**.
4. Google emails you a download link in 30 minutes to several hours. The zip is usually 100-500 MB.
5. Download it. Don't unzip — Echo reads zips directly.

---

## 2. (Optional) Request your Spotify Extended Streaming History

Echo can ingest Spotify in addition to YouTube for cross-modal queries
(e.g. "when was I listening to a lot of music but watching very little YouTube?").

1. Go to <https://spotify.com/account/privacy>.
2. Scroll to **Download your data** → check **Extended streaming history** → request.
3. Spotify takes **up to 30 days** to email you the export. Continue with the
   YouTube-only setup in the meantime; you can add Spotify later by re-running
   `echo init` or editing `~/.echo/config.toml`.

---

## 3. Clone + install

```bash
git clone https://github.com/<your-fork>/echo.git
cd echo

python -m venv .venv
.venv\Scripts\activate            # Windows (PowerShell)
# source .venv/bin/activate       # macOS / Linux

pip install -e .
```

`pip install -e .` installs the `echo-archaeology` package in editable mode —
the `echo` CLI is now on your PATH (or invokable as `python -m echo.cli.main`
if your venv's Scripts dir isn't on PATH).

**Verify:**
```bash
echo --version           # echo 0.1.0
echo --help              # lists all subcommands
```

If `echo` isn't found, your venv's Scripts dir isn't on PATH. Either fix that,
or just use `python -m echo.cli.main` everywhere — it works identically.

---

## 4. First-run setup wizard

```bash
echo init
```

The wizard walks you through 5 sections:

1. **Data directory** — defaults to `~/.echo/` (Windows: `%USERPROFILE%\.echo\`). Press enter to accept.
2. **Source archive paths** — point at the Takeout / Spotify zips you downloaded in Steps 1 and 2. Skip any you don't have.
3. **YouTube metadata enrichment** — enter your YouTube API key. Skip if you don't want metadata (chapters and reflections still work; you just won't see video categories).
4. **Spotify track enrichment** — enter your Spotify Client ID + Secret. Skip if you skipped Spotify.
5. **LLM provider** — pick Anthropic (recommended for the agent), OpenAI, or OpenRouter. Enter your API key.

The wizard writes `~/.echo/config.toml` (preferences) and `~/.echo/.env`
(secrets) and exits. You can re-run it any time to update — it preserves
existing values and only overwrites what you change.

**Verify with `echo doctor`:**
```bash
echo doctor
```

This prints your current config, every API key set (showing only the last 4
chars), every configured zip path with [OK / NOT FOUND / missing], and the
current DB schema. Use it whenever something feels off.

---

## 5. Run the pipeline

```bash
echo run
```

This executes the six pipeline steps in order:

```
ingest -> enrich -> detect -> signals -> reflect -> embed
```

| Step | What it does | Cost | Time |
|---|---|---|---|
| `ingest` | Read Takeout + Spotify zips into `echo.db`. | $0 | ~5-15s |
| `enrich` | Fetch video metadata from YouTube API. Cached forever after first run. | $0 (within 10K daily quota) | ~30s for a fresh 6K-watch history |
| `detect` | PELT changepoint detection on weekly viewing signals → chapters. | $0 | <2s |
| `signals` | Engagement scoring (session, autoplay proxy, search-driven, rewatch). | $0 | <5s |
| `reflect` | GPT-4o writes a 200-300 word narrative per chapter + an autobiography. | ~$0.15 for 16 chapters + autobiography | ~3-5 min |
| `embed` | text-embedding-3-small over 4 corpora into `~/.echo/lancedb/`. | ~$0.01-0.05 | ~30-60s |

**Expected output:** progress per step + "Pipeline complete. Echo is ready to query." at the end.

**If a step fails**, fix the cause shown in the error message and resume with
`echo run --from <step>` instead of restarting from the top.

**To preview reflections before spending tokens:**
```bash
echo reflect --dry-run                     # prints all chapter prompts, no API call
echo reflect --dry-run --autobiography     # prints the autobiography prompt
```

**To skip Spotify enrichment** (e.g. while waiting for your Spotify export to ship):
```bash
echo run --skip-enrich-spotify
```

**To skip Last.fm music-meta enrichment** (mood/genre dimension; requires a free `LASTFM_API_KEY`):
```bash
echo run --skip-enrich-music-meta
```
If `LASTFM_API_KEY` is unset, this step is skipped automatically with a one-line setup hint. Get a free key at `last.fm/api/account/create` (instant, no review) to unlock cross-modal mood queries like "when was I in a melancholy phase, and what was I watching at the same time?"

---

## 6. Browse / query your data

Three options, pick whichever fits.

### 6a. `echo serve` (simplest, single process)

```bash
echo serve
```

Starts the FastAPI backend + bundled SvelteKit UI on `http://localhost:8000`.
Open in your browser, ask Echo Speaks a question, watch the 20-round ReAct
loop unfold with findings + cost footer in real time.

> **Note:** if you see "UI not bundled" on startup, build the UI once:
> ```bash
> cd ui && npm install && npm run build && cp -r build ../src/echo/ui/dist
> ```
> then re-run `echo serve`. (This is a one-time step until the UI build is
> wired into `pip install`.)

### 6b. `docker compose up` (containerized)

```bash
docker compose up --build
```

Starts the API at `http://localhost:8000` and the UI dev server at
`http://localhost:5173`. The api container reads `~/.echo/` if you set:

```bash
export ECHO_DATA_DIR=~/.echo            # Linux / macOS
$env:ECHO_DATA_DIR = "$HOME\.echo"      # Windows PowerShell
```

before running `docker compose up`. Without the override, it mounts the
current directory (the legacy pre-packaging layout — works if you still keep
`echo.db` at the repo root).

### 6c. Datasette (raw SQL browser)

```bash
./run.sh                   # macOS / Linux
run.bat                    # Windows
```

Opens Datasette at <http://127.0.0.1:8001> for raw SQL exploration with the
17 canned queries in `metadata.yaml`.

---

## 7. (Optional) Add life-context annotations

Some chapter reflections will misinterpret your data without context Echo
can't infer (which school you went to, calendar labels you reused for two
different things, an illness or move that explains a viewing pattern).

```bash
cp annotations.example.yaml ~/.echo/private/annotations.yaml
# edit the file to add your own annotations
echo reflect                       # re-run; annotations are now injected into prompts
```

Each annotation is a date range + free-text note. See
`annotations.example.yaml` for the schema. The file stays in `~/.echo/private/`
which is fully local to your machine.

---

## 8. (Optional) Migrating from a pre-packaging Echo install

If you used Echo before this packaging release (data at `D:/Projects/Echo/echo.db`
rather than `~/.echo/echo.db`), one command migrates everything:

```bash
echo migrate-data --from /path/to/your/old/Echo --dry-run    # preview
echo migrate-data --from /path/to/your/old/Echo              # COPY (safe)
echo migrate-data --from /path/to/your/old/Echo --move -y    # MOVE (no source dup)
```

This relocates `echo.db`, `lancedb/`, and `private/annotations.yaml` into
your new data dir so you don't have to re-run enrichment (10K of YouTube
quota) or reflections (~$5 of GPT-4o spend).

---

## Security model

### `UNSAFE_PYTHON_SANDBOX`

Echo Speaks can execute Python code via the `execute_python` tool. **Disabled
by default** (`UNSAFE_PYTHON_SANDBOX=false`). When enabled, the agent runs
arbitrary Python in the server process — useful for ad-hoc analysis the agent
designs on the fly, but no sandboxing.

**Only enable on trusted local machines where you are the only user.** Never
on a shared network. Docker Compose forces it to `false` regardless of env;
fix that only if you understand the implications.

### Personal data

`echo.db` is your full watch / search / calendar / GPay history. It's
gitignored everywhere Echo writes it (`~/.echo/`, the repo root if you used
the pre-packaging layout, and the legacy `_data/` directory).

Same goes for `~/.echo/lancedb/`, `~/.echo/private/`, your raw Takeout zips,
and `~/.echo/.env`. Never commit any of them; never share them.

---

## Running tests

```bash
pytest tests/ -v
```

Tests use the conftest.py shim that points `ECHO_DATA_DIR` at the repo root,
so two integration tests (`test_pelt_happy_path`, `test_clustering_happy_path`)
run against your actual `echo.db` and `lancedb/`. Expect ~105 passing + 4
pre-existing known-flaky tests (`test_enrich_videos` × 3 — fixture DB lacks
`watch_signals` table; `test_youtube_missing_api_key` — env-isolation issue
with a live API key on the host). Neither set is a regression.

Proper fixture-based tests are tracked as a Session 2 follow-up.

---

## Troubleshooting

**`echo` command not found** — Your venv's `Scripts/` (Windows) or `bin/` (Unix)
dir isn't on PATH. Activate the venv (`.venv\Scripts\activate` /
`source .venv/bin/activate`) or just use `python -m echo.cli.main ...`
which works identically.

**`echo init` exits without prompting** — You're piped-in (no TTY).
Use `--non-interactive` with explicit flags:
```bash
echo init --non-interactive --youtube-zip /path/to/takeout.zip
```

**`echo run` fails at `ingest` with "no such file"** — Run `echo doctor`
to see which zip paths it thinks are configured. Re-run `echo init` to
correct them, or edit `~/.echo/config.toml` directly.

**`echo enrich` returns HTTP 403** — YouTube API daily quota exceeded
(10,000 units, ~10K videos). Wait for the midnight PT reset and try again.
The metadata cache means the next run only fetches what was missed.

**`echo reflect` quotes a different language than you expect** — The
system prompt is tuned for an Indian student aged 13-23. For other contexts,
edit the `CHAPTER_PROMPT_SYSTEM` and `AUTOBIOGRAPHY_SYSTEM` strings near the
top of `src/echo/pipeline/reflect.py`.

**Langfuse traces not showing** — The env var is `LANGFUSE_HOST` (not
`LANGFUSE_BASE_URL`). The latter is silently ignored. Check `~/.echo/.env`.

**Calendar context missing for chapters before 2022** — Calendar data in
Google Takeout only goes back to ~2022. Older chapters skip the LIFE CONTEXT
section in reflections. This is correct, not a bug.

**`docker compose up` says "echo.db not found"** — Either set
`ECHO_DATA_DIR=~/.echo` (where your data lives now) before `docker compose
up`, or fall back to mounting your current dir by running `docker compose up`
from a directory that contains your `echo.db`.
