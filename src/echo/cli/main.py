"""Echo CLI entry point.

After `pip install -e .` this is reachable as the `echo` command. Subcommands
fall into two groups:

  Setup + orchestration:
    echo init                First-run interactive wizard
    echo init --non-interactive [...]  Scripted setup for CI / containers
    echo run [--from STEP]   Full pipeline (ingest -> ... -> embed)
    echo doctor              Sanity-check the install

  Individual pipeline steps:
    echo ingest              Run ingest only
    echo enrich              YouTube API enrichment
    echo enrich-spotify      Spotify API enrichment
    echo enrich-music-meta   Last.fm tag enrichment (mood/genre dimension)
    echo detect              PELT changepoint detection
    echo signals             Engagement signal scoring
    echo reflect             GPT-4o narrative reflection (use --dry-run first)
    echo embed               LanceDB vector embedding
    echo view-reflections    Render reflections to a static HTML page

Run `echo <subcommand> --help` for per-command flags.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Optional

import typer

from echo import __version__
from echo.config import EchoConfig, load_config
from echo.cli.wizard import run_wizard, save_config
from echo.cli.migrate import migrate_data as _migrate_data

app = typer.Typer(
    name="echo",
    help="Personal data archaeology - analyze your own YouTube + Spotify + Calendar history.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"echo {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Echo CLI root callback. Adds --version, otherwise hands off to subcommands."""
    pass


# ── Setup + orchestration ───────────────────────────────────────────────────


@app.command()
def init(
    non_interactive: bool = typer.Option(
        False, "--non-interactive",
        help="Skip prompts; use existing config + env values + flags only.",
    ),
    data_dir: Optional[Path] = typer.Option(
        None, "--data-dir", help="(non-interactive) Override data directory.",
    ),
    youtube_zip: Optional[Path]  = typer.Option(None, "--youtube-zip"),
    activity_zip: Optional[Path] = typer.Option(None, "--activity-zip"),
    calendar_zip: Optional[Path] = typer.Option(None, "--calendar-zip"),
    spotify_zip: Optional[Path]  = typer.Option(None, "--spotify-zip"),
) -> None:
    """First-run setup wizard. Writes ~/.echo/config.toml and ~/.echo/.env.

    Interactive by default. Pass --non-interactive for scripted setup (useful in
    CI / containers / a smoke test); paths can be set via the flags above and
    secrets via the standard env vars (ANTHROPIC_API_KEY etc.).
    """
    cfg = load_config()

    if non_interactive:
        if data_dir:    cfg.data_dir = data_dir.expanduser()
        if youtube_zip:  cfg.takeout.youtube_zip  = youtube_zip.expanduser()
        if activity_zip: cfg.takeout.activity_zip = activity_zip.expanduser()
        if calendar_zip: cfg.takeout.calendar_zip = calendar_zip.expanduser()
        if spotify_zip:  cfg.takeout.spotify_zip  = spotify_zip.expanduser()
        typer.echo("Non-interactive init: using current config + flag overrides + env.")
    else:
        cfg = run_wizard(cfg)

    config_path, env_path = save_config(cfg)
    typer.echo(f"\nWrote: {config_path}")
    typer.echo(f"Wrote: {env_path}")
    typer.echo("\nNext: drop your Takeout / Spotify zips into the configured paths,")
    typer.echo("      then run `echo run` to build your archive.")


# Pipeline step ordering for `echo run`. Keep in sync with the design doc.
# enrich-music-meta is fail-soft on missing LASTFM_API_KEY (prints message and
# returns rather than sys.exit) so it can safely sit in the default order
# without breaking users who haven't configured a Last.fm key.
_PIPELINE_STEPS = (
    "ingest", "enrich", "enrich-spotify", "enrich-music-meta",
    "detect", "signals", "reflect", "embed",
)


def _module_for(step: str):
    """Resolve a pipeline step name to its imported module."""
    module_name = step.replace("-", "_")
    return importlib.import_module(f"echo.pipeline.{module_name}")


@app.command()
def run(
    from_step: Optional[str] = typer.Option(
        None, "--from", help=f"Resume from a step (one of: {', '.join(_PIPELINE_STEPS)}).",
    ),
    skip_enrich_spotify: bool = typer.Option(
        False, "--skip-enrich-spotify",
        help="Skip Spotify enrichment (useful if you haven't configured a Spotify app yet).",
    ),
    skip_enrich_music_meta: bool = typer.Option(
        False, "--skip-enrich-music-meta",
        help="Skip Last.fm tag enrichment (mood/genre dimension).",
    ),
) -> None:
    """Run the full pipeline: ingest -> enrich -> detect -> signals -> reflect -> embed.

    Each step is idempotent on its own, so `echo run` is safe to re-run from
    scratch. --from skips earlier steps that have already finished successfully.
    """
    cfg = load_config()

    if from_step and from_step not in _PIPELINE_STEPS:
        typer.echo(f"ERROR: unknown step {from_step!r}.")
        typer.echo(f"Valid: {', '.join(_PIPELINE_STEPS)}")
        raise typer.Exit(code=1)

    steps = list(_PIPELINE_STEPS)
    if from_step:
        steps = steps[steps.index(from_step):]
    if skip_enrich_spotify and "enrich-spotify" in steps:
        steps.remove("enrich-spotify")
    if skip_enrich_music_meta and "enrich-music-meta" in steps:
        steps.remove("enrich-music-meta")

    typer.echo(f"Running pipeline: {' -> '.join(steps)}\n")
    for step in steps:
        typer.echo(f"==> {step}")
        mod = _module_for(step)
        try:
            mod.run(cfg)
        except SystemExit as e:
            # A pipeline step exited with sys.exit(); surface a clean message.
            if e.code:
                typer.echo(f"\nStep '{step}' aborted (exit code {e.code}).")
                typer.echo(f"Fix the cause above, then resume with: echo run --from {step}")
                raise typer.Exit(code=int(e.code or 1))
        typer.echo("")

    typer.echo("Pipeline complete. Echo is ready to query.")


@app.command()
def doctor() -> None:
    """Sanity-check the install: paths, configured zips, API keys, db schema."""
    cfg = load_config()

    typer.echo("== Echo doctor ==\n")
    typer.echo(f"Version:        {__version__}")
    typer.echo(f"Python:         {sys.version.split()[0]}")
    typer.echo(f"Data dir:       {cfg.data_dir}  "
               f"({'OK' if cfg.data_dir.exists() else 'will be created on first write'})")
    typer.echo(f"DB path:        {cfg.db_path}  ({'present' if cfg.db_path.exists() else 'absent'})")
    typer.echo(f"LanceDB:        {cfg.lancedb_path}  ({'present' if cfg.lancedb_path.exists() else 'absent'})")
    typer.echo(f"Annotations:    {cfg.annotations_path}  ({'present' if cfg.annotations_path.exists() else 'absent'})")
    typer.echo("")
    typer.echo("Source archives:")
    for label, path in (
        ("  youtube_zip ", cfg.takeout.youtube_zip),
        ("  activity_zip", cfg.takeout.activity_zip),
        ("  calendar_zip", cfg.takeout.calendar_zip),
        ("  spotify_zip ", cfg.takeout.spotify_zip),
    ):
        status = "missing" if not path else ("OK" if path.exists() else "NOT FOUND")
        typer.echo(f"{label}: {path or '(unset)'}  [{status}]")
    typer.echo("")
    typer.echo(f"Enrichments enabled: {cfg.enrichments or '(none)'}")
    typer.echo(f"LLM provider:        {cfg.llm_provider}")
    typer.echo("")
    typer.echo("API keys (4-char tail shown if set):")
    for label, key in (
        ("  YOUTUBE      ", cfg.api_keys.youtube),
        ("  OPENAI       ", cfg.api_keys.openai),
        ("  OPENROUTER   ", cfg.api_keys.openrouter),
        ("  ANTHROPIC    ", cfg.api_keys.anthropic),
        ("  SPOTIFY_ID   ", cfg.api_keys.spotify_client_id),
        ("  SPOTIFY_SEC  ", cfg.api_keys.spotify_client_secret),
        ("  LASTFM       ", cfg.api_keys.lastfm),
        ("  LANGFUSE_PUB ", cfg.api_keys.langfuse_public),
        ("  LANGFUSE_SEC ", cfg.api_keys.langfuse_secret),
    ):
        if key:
            tail = key[-4:] if len(key) > 4 else "***"
            typer.echo(f"{label}: set (***{tail})")
        else:
            typer.echo(f"{label}: not set")
    typer.echo("")

    # DB schema sanity (only if DB exists)
    if cfg.db_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(cfg.db_path))
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()]
            conn.close()
            typer.echo(f"DB tables ({len(tables)}): {', '.join(tables) or '(empty)'}")
        except Exception as e:
            typer.echo(f"DB read error: {e}")


# ── Pipeline step subcommands ───────────────────────────────────────────────


@app.command()
def ingest() -> None:
    """Ingest Takeout + Spotify archives into echo.db."""
    from echo.pipeline import ingest as mod
    mod.run(load_config())


@app.command()
def enrich(
    key: Optional[str] = typer.Option(None, "--key", help="Override YouTube API key for this run."),
) -> None:
    """YouTube metadata enrichment (title, category, duration, tags)."""
    from echo.pipeline import enrich as mod
    mod.run(load_config(), api_key_override=key)


@app.command("enrich-spotify")
def enrich_spotify(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show pending count, no API calls."),
    limit: Optional[int] = typer.Option(None, "--limit", help="Enrich at most N pending tracks."),
) -> None:
    """Spotify metadata enrichment (duration, explicit, URI verify)."""
    from echo.pipeline import enrich_spotify as mod
    mod.run(load_config(), dry_run=dry_run, limit=limit)


@app.command("enrich-music-meta")
def enrich_music_meta(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show counts, no API calls."),
    top_n:   int  = typer.Option(500, "--top-n", help="Tier 2 depth (most-played tracks for track-level tags)."),
) -> None:
    """Last.fm tag enrichment: per-artist (Tier 1) + per-track top-N (Tier 2)."""
    from echo.pipeline import enrich_music_meta as mod
    mod.run(load_config(), dry_run=dry_run, top_n=top_n)


@app.command()
def detect(
    penalty: float = typer.Option(3.0, "--penalty", help="PELT penalty; higher = fewer chapters."),
    plot: bool = typer.Option(False, "--plot", help="Save weekly_signal.png alongside the db."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print chapters; don't write to DB."),
) -> None:
    """PELT changepoint detection over weekly signals."""
    from echo.pipeline import detect as mod
    mod.run(load_config(), penalty=penalty, plot=plot, dry_run=dry_run)


@app.command()
def signals() -> None:
    """Compute watch_signals + spotify_signals (engagement scoring)."""
    from echo.pipeline import signals as mod
    mod.run(load_config())


@app.command()
def reflect(
    dry_run: bool = typer.Option(False, "--dry-run", help="Print prompts; no API calls."),
    chapter: Optional[int] = typer.Option(None, "--chapter", help="Reflect on one chapter by number."),
    autobiography: bool = typer.Option(False, "--autobiography", help="Full arc synthesis across all chapters."),
) -> None:
    """GPT-4o narrative reflection. ALWAYS run --dry-run first to preview prompts."""
    from echo.pipeline import reflect as mod
    mod.run(load_config(), dry_run=dry_run, chapter=chapter, autobiography=autobiography)


@app.command()
def embed(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show counts; no API calls."),
    table: Optional[str] = typer.Option(None, "--table", help="Embed one table only (reflections / videos / searches / google_searches)."),
) -> None:
    """LanceDB vector embedding (4 corpora; provider via config)."""
    from echo.pipeline import embed as mod
    mod.run(load_config(), dry_run=dry_run, table=table)


@app.command("view-reflections")
def view_reflections(
    no_open: bool = typer.Option(False, "--no-open", help="Write file; don't open browser."),
) -> None:
    """Render the reflections HTML viewer at <data_dir>/reflections_viewer.html."""
    from echo.cli import view_reflections as mod
    mod.run(load_config(), no_open=no_open)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind interface (use 0.0.0.0 for LAN access)."),
    port: int = typer.Option(8000, "--port", help="TCP port."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (dev mode)."),
) -> None:
    """Start the FastAPI backend, mounting the bundled SvelteKit UI at /.

    The UI is shipped pre-built inside the wheel at src/echo/ui/dist/. If
    that directory is empty (which it is on a fresh `pip install -e .`),
    the API still starts but no UI is served - run a one-time build:

        cd ui && npm install && npm run build && cp -r build ../src/echo/ui/dist

    Then this command serves the full Echo Speaks landing page at the host
    address it prints.
    """
    from echo.cli.serve import run as _serve
    _serve(host=host, port=port, reload=reload)


@app.command("migrate-data")
def migrate_data(
    source: Path = typer.Option(
        ..., "--from", "-f",
        help="Source directory (e.g. an old D:/Projects/Echo clone with echo.db at root).",
    ),
    move: bool = typer.Option(False, "--move", help="Move files instead of copying (faster; deletes source)."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing destination files."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plan; touch nothing."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Move (or copy) pre-packaging Echo state into the configured data dir.

    Migrates echo.db (+ wal/shm), lancedb/, and private/annotations.yaml from
    a prior install (where they lived at repo root) into ~/.echo/ (or
    wherever ECHO_DATA_DIR points). One-time op - saves re-running 10K of
    YouTube enrichment quota and ~$5 of GPT-4o reflection cost.
    """
    cfg = load_config()
    _migrate_data(source=source, data_dir=cfg.data_dir,
                  move=move, force=force, dry_run=dry_run, yes=yes)


if __name__ == "__main__":
    app()
