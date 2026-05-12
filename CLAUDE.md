# Echo — Project Instructions for Claude Code

## What this project is

Echo is a deeply personal data archaeology project — 6+ years of Aditya's digital life
(YouTube watches, searches, calendar, transactions) ingested into a SQLite database and
analysed for behavioral patterns and narrative reflection. The data spans ages 13–23.
Treat insights from it with appropriate weight. This is not a demo project.

**Owner:** Aditya Arya (23, Indian, IST timezone)
**Stack:** Python + SQLite (sqlite-utils) + Datasette + ruptures + OpenAI GPT-4o
**DB:** `D:\Projects\Echo\echo.db` — never committed to git (personal data)

---

## Pipeline order

Scripts must run in this exact order. Each depends on the previous.

```
ingest.py → enrich.py → detect.py → signals.py → reflect.py
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
| `ingest.py` | Loads all 8 data sources from 3 zip files into echo.db |
| `enrich.py` | YouTube Data API enrichment (video metadata) |
| `detect.py` | Layer 2: PELT changepoint detection → chapters table |
| `signals.py` | Engagement scoring → watch_signals table |
| `reflect.py` | Layer 3: GPT-4o narrative reflection → reflections table |
| `RUNBOOK.md` | How to operate the pipeline |
| `DATA.md` | What every table and column means |
| `metadata.yaml` | Datasette canned queries (17 queries for Layer 1 browser) |
| `run.bat` | Launches Datasette on 127.0.0.1:8001 |
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
- `chapter_fingerprints` fingerprint mapping in `reflect.py:assemble_chapter_context` uses
  positional `cf.*` zip. If schema changes, update the column name list in sync.
- `watch_later` is a snapshot at Takeout export date — `was_bookmarked` reflects that
  snapshot, not the state at watch time.
- `is_autoplay` is a same-channel proxy only. True autoplay rate is higher.
- Calendar data only exists from 2022 onwards. Chapters 1–4 (2019–2021) will show no
  calendar context in reflect.py. This is correct, not a bug.
- `enrich.py` YouTube API quota: 10,000 units/day. If it hits 403, wait for midnight PT reset.

---

## Pending (as of 2026-05-13)

- **OpenAI API key** — YC Starter AI Stack credits pending. Once available: add to `.env`,
  run `pip install openai`, then `python reflect.py --dry-run --chapter 15` to preview.
- **Spotify ingestion** — data expected ~2026-05-17. New table in ingest.py when ready.
- **lancedb embedding index** — blocked on OpenAI key (text-embedding-3-small).
- **Datasette metadata.yaml** — add queries for watch_signals and reflections tables.

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
