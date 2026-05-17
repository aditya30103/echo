"""Echo CLI — Typer app and subcommands.

Entry point: `echo` command (defined in `echo.cli.main:app`, wired via
pyproject.toml [project.scripts]).

Subcommands (filled in across Steps P2.5 onwards):
  echo init               First-run setup wizard
  echo run                Run the full pipeline (ingest → enrich → ... → embed)
  echo ingest             Just ingest
  echo enrich             Just YouTube enrichment
  echo enrich-spotify     Just Spotify enrichment
  echo detect             Just changepoint detection
  echo signals            Just engagement signals
  echo reflect            Just GPT-4o reflections (NEVER without --dry-run first)
  echo embed              Just LanceDB embeddings
  echo view-reflections   Open static HTML viewer (was viewer.py)
  echo serve              Start FastAPI + serve baked UI at http://localhost:8000
  echo doctor             Sanity check: deps, paths, API keys, schema
  echo migrate-data       One-time: move pre-packaging state into ~/.echo/
"""
