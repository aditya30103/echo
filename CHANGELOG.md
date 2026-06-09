# Changelog

All notable changes to **echo-archaeology** are documented here. The format
loosely follows [Keep a Changelog](https://keepachangelog.com); versions follow
[semantic versioning](https://semver.org).

## [0.1.0] — 2026-06-09

First public release. Echo turns your Google Takeout and Spotify history into a
queryable local database analysed by an autonomous Claude-powered agent — it finds
behavioral chapters, writes narrative reflections, and answers free-form questions
about your own data, entirely on your machine.

### Added
- **Packaged CLI** (`echo` command). `echo init` wizard, the full pipeline
  (`ingest → enrich → enrich-spotify → enrich-music-meta → detect → signals →
  reflect → embed`), `echo doctor`, and `echo serve` (FastAPI backend + bundled
  SvelteKit UI on a single port).
- **Echo Speaks** — an autonomous ReAct agent that explores your data over many
  rounds and synthesizes surprising findings, with a narrative-blind first phase
  so hypotheses form from raw behavior, not prior reflections.
- **Local Ollama provider** — run the agent and chat with **no cloud API key**
  by setting `OLLAMA_BASE_URL`. Cloud keys (Anthropic / OpenAI / OpenRouter) are
  preferred automatically when present.
- **Cross-modal music + video analysis** via Last.fm tag enrichment and per-table
  LanceDB vector search.

### Notes
- All user data is personal and stays local; `.env`, `echo.db`, and raw exports
  are never committed.
- Optional enrichment steps (Spotify, Last.fm, YouTube metadata) are fail-soft —
  the pipeline continues without their keys.
