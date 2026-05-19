# Echo — Quick Install Guide

> Hand this file to your AI assistant (Claude Code, Cursor, Copilot) and say
> "follow INSTALL.md to set up Echo on this machine." For the full walkthrough,
> see [SETUP.md](./SETUP.md).

---

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | `python --version` to check |
| Node.js | 20+ | Only needed if you want to rebuild the UI; not needed to run `echo serve` |
| Disk | ~5 GB | For the database, vector index, and your Takeout zip |
| Google Takeout export | — | Download at <https://takeout.google.com>. Select: **YouTube and YouTube Music** + **My Activity** + **Google Calendar**. Format: JSON. |

---

## 2. Install

```bash
git clone https://github.com/<you>/echo.git
cd echo
pip install -e .
```

Or, once on PyPI (coming soon):

```bash
pip install echo-archaeology
```

---

## 3. Init — first-run setup wizard

```bash
echo init
```

The wizard has five sections:

1. **Takeout** — path to your Google Takeout zip
2. **Spotify** — path to your Spotify Extended Streaming History zip (optional)
3. **API keys** — enter any keys you have; all are optional (see table below)
4. **Enrichment toggles** — confirm which optional steps to enable
5. **LLM provider** — pick Anthropic (recommended), OpenAI, or OpenRouter

For scripted / CI use: `echo init --non-interactive`

---

## 4. What's optional

You can run Echo with nothing but a Takeout zip. API keys unlock additional
features. You can add any key later and re-run only that step.

| Key | What it unlocks | Can add later? |
|---|---|---|
| `ANTHROPIC_API_KEY` | **Echo Speaks** agent — the main feature | Yes — `echo run --from embed` |
| `OPENAI_API_KEY` | Chapter reflections (GPT-4o) + embeddings | Yes — `echo run --from reflect` |
| `OPENROUTER_API_KEY` | Alternative to OpenAI/Anthropic | Yes |
| `YOUTUBE_API_KEY` | Video metadata enrichment (title, channel, views) | Yes — `echo enrich` |
| `SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET` | Spotify track metadata enrichment | Yes — `echo enrich-spotify` |
| `LASTFM_API_KEY` | Music mood/genre tags (cross-modal queries) | Yes — `echo enrich-music-meta` |
| `LANGFUSE_*` | Agent tracing dashboard | Yes — add to .env any time |

**Minimum viable install:** Takeout zip only → `echo run` gives you chapters +
signals. No reflections, no agent. Still interesting; the Binge Sessions and
Agency Map views work.

---

## 5. Run the pipeline

```bash
echo run
```

Order: `ingest → enrich → enrich-spotify → enrich-music-meta → detect → signals → reflect → embed`

Expected times on a typical laptop:

| Step | Time | Notes |
|---|---|---|
| `ingest` | 1–5 min | Depends on Takeout zip size |
| `enrich` | 1–10 min | YouTube API; 10K quota/day |
| `enrich-spotify` | ~72 min | 4K tracks at 1 req/s |
| `enrich-music-meta` | ~30 min | Last.fm; rate-limited automatically |
| `detect` | < 1 min | PELT changepoint detection |
| `signals` | < 1 min | Engagement scoring |
| `reflect` | 5–20 min | GPT-4o; costs ~$0.15 for 16 chapters |
| `embed` | 2–5 min | OpenAI embeddings; ~$0.01 |

Run a single step: `echo run --from reflect` (skips everything before it).

---

## 6. Spotify timing — plan ahead

- **Extended History export**: request at <https://www.spotify.com/account/privacy>.
  Spotify takes **~30 days** to ship it. Request now if you want Spotify data.
- **Enrichment quota**: the Spotify Developer API allows ~1 req/s with a Client
  Credentials app. 4,000 tracks ≈ 72 minutes. If you get a `429`, wait for
  midnight PT and re-run (`echo enrich-spotify` is idempotent).

---

## 7. Serve the UI

```bash
echo serve          # FastAPI + bundled SvelteKit on http://localhost:8000
```

Or with Docker:

```bash
ECHO_DATA_DIR=~/.echo docker compose up
```

---

## 8. Personalise reflections

Chapter reflections improve significantly with personal context. Copy the template
and fill in your life milestones:

```bash
cp annotations.example.yaml private/annotations.yaml
# edit private/annotations.yaml — schools, jobs, moves, relationships, etc.
echo run --from reflect   # re-run reflect with your context
```

The file is gitignored — it never leaves your machine.

---

## 9. Troubleshooting quick-ref

| Problem | Fix |
|---|---|
| `echo doctor` shows red | Run it — it tells you exactly what's missing and what to do |
| YouTube API 403 | Quota exceeded (10K/day). Wait for midnight PT reset. |
| Spotify 429 | Rate limit. Wait for midnight PT. `echo enrich-spotify` resumes where it stopped. |
| `echo serve` says "UI not bundled" | Run `cd ui && npm run build` (Node.js required) |
| Reflections sound generic | Fill in `private/annotations.yaml` — see step 8 |
| `LANGFUSE_HOST` not working | Use `LANGFUSE_HOST`, not `LANGFUSE_BASE_URL` |

Full troubleshooting in [SETUP.md](./SETUP.md).
