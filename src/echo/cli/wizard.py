"""Interactive setup wizard backing `echo init`.

Extracted from cli/main.py so the wizard logic is testable independent of
Typer's stdio. The init command imports run_wizard() and save_config()
and wires them to argv + stdin.

Design:
- run_wizard(initial_config) returns an updated EchoConfig (does NOT persist).
- save_config(config) writes ~/.echo/config.toml + ~/.echo/.env.

The split lets tests construct a fake initial config, monkeypatch typer.prompt
to feed scripted input, and assert on the returned config without touching
disk.
"""

from __future__ import annotations

from pathlib import Path

import typer

from echo.config import EchoConfig, LLMProvider


def _prompt_path(label: str, default: str = "") -> Path | None:
    """Prompt for a filesystem path. Returns None if user just presses enter."""
    raw = typer.prompt(label, default=default, show_default=bool(default))
    raw = raw.strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _prompt_secret(label: str) -> str | None:
    """Prompt for a secret. Returns None if user just presses enter (skipped)."""
    raw = typer.prompt(label, default="", hide_input=True, show_default=False)
    raw = raw.strip()
    return raw or None


def run_wizard(initial: EchoConfig) -> EchoConfig:
    """Walk the user through five sections, returning a fully populated config.

    Reads stdin via typer.prompt - tests can monkeypatch typer.prompt to bypass.
    Caller is responsible for save_config() afterward.
    """
    cfg = initial

    typer.echo("Echo first-run setup. Press Ctrl+C any time to abort.")
    typer.echo("Most prompts have safe defaults - press enter to accept.\n")

    # ── 1/5 Data directory ─────────────────────────────────────────────────
    typer.echo(f"[1/5] Data directory")
    typer.echo("  Where Echo stores its database, vector index, and config.")
    data_dir = typer.prompt("  Path", default=str(cfg.data_dir))
    cfg.data_dir = Path(data_dir).expanduser()

    # ── 2/5 Takeout paths ──────────────────────────────────────────────────
    typer.echo(f"\n[2/5] Source archives")
    typer.echo("  Paths to your Google Takeout + Spotify exports.")
    typer.echo("  Leave a prompt blank to skip that source.")
    cfg.takeout.youtube_zip  = _prompt_path("  YouTube Takeout zip")
    cfg.takeout.activity_zip = _prompt_path("  Google My Activity zip")
    cfg.takeout.calendar_zip = _prompt_path("  Calendar Takeout zip")
    cfg.takeout.spotify_zip  = _prompt_path("  Spotify Extended History zip")

    # ── 3/5 YouTube enrichment ─────────────────────────────────────────────
    typer.echo(f"\n[3/5] YouTube metadata enrichment")
    typer.echo("  Fetches title / category / duration / tags from the YouTube API.")
    typer.echo("  Free tier: 10,000 units/day quota.")
    if typer.confirm("  Enable?", default=True):
        if "youtube" not in cfg.enrichments:
            cfg.enrichments.append("youtube")
        typer.echo("  Get an API key at https://console.cloud.google.com/apis/credentials")
        cfg.api_keys.youtube = _prompt_secret("  YOUTUBE_API_KEY")
    else:
        cfg.enrichments = [e for e in cfg.enrichments if e != "youtube"]

    # ── 4/5 Spotify enrichment ─────────────────────────────────────────────
    typer.echo(f"\n[4/5] Spotify track enrichment")
    typer.echo("  Fetches duration / explicit flag via Spotify search API.")
    typer.echo("  Skip if you skipped the Spotify zip above.")
    if typer.confirm("  Enable?", default=False):
        if "spotify" not in cfg.enrichments:
            cfg.enrichments.append("spotify")
        typer.echo("  Create an app at https://developer.spotify.com/dashboard")
        cfg.api_keys.spotify_client_id     = _prompt_secret("  SPOTIFY_CLIENT_ID")
        cfg.api_keys.spotify_client_secret = _prompt_secret("  SPOTIFY_CLIENT_SECRET")
    else:
        cfg.enrichments = [e for e in cfg.enrichments if e != "spotify"]

    # ── 5/5 LLM provider ───────────────────────────────────────────────────
    typer.echo(f"\n[5/5] LLM provider for reflections + Echo Speaks agent")
    typer.echo("  Options: anthropic (recommended for the agent),")
    typer.echo("           openai     (gpt-4o, also used by reflect.py),")
    typer.echo("           openrouter (alternative path for OpenAI calls).")
    provider = typer.prompt("  Provider", default=cfg.llm_provider)
    if provider not in ("anthropic", "openai", "openrouter"):
        typer.echo(f"  Unknown provider {provider!r} - defaulting to 'anthropic'.")
        provider = "anthropic"
    cfg.llm_provider = provider  # type: ignore[assignment]

    if provider == "anthropic":
        cfg.api_keys.anthropic = _prompt_secret("  ANTHROPIC_API_KEY")
    elif provider == "openai":
        cfg.api_keys.openai = _prompt_secret("  OPENAI_API_KEY")
    else:  # openrouter
        cfg.api_keys.openrouter = _prompt_secret("  OPENROUTER_API_KEY")

    return cfg


def save_config(cfg: EchoConfig) -> tuple[Path, Path]:
    """Persist cfg to <data_dir>/config.toml + <data_dir>/.env.

    Returns (config_path, env_path) for the caller to display.
    """
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    config_path = cfg.data_dir / "config.toml"
    env_path    = cfg.data_dir / ".env"

    config_path.write_text(_render_toml(cfg), encoding="utf-8")
    env_path.write_text(_render_env(cfg), encoding="utf-8")
    return config_path, env_path


def _render_toml(cfg: EchoConfig) -> str:
    """Serialize the non-secret parts of cfg to TOML."""
    lines = [
        "# Echo configuration. Generated by `echo init`.",
        "# Secrets (API keys) live alongside this file in .env, not here.",
        "",
        "[takeout]",
    ]
    for name, value in (
        ("youtube_zip",  cfg.takeout.youtube_zip),
        ("activity_zip", cfg.takeout.activity_zip),
        ("calendar_zip", cfg.takeout.calendar_zip),
        ("spotify_zip",  cfg.takeout.spotify_zip),
    ):
        if value:
            lines.append(f'{name} = "{value.as_posix()}"')

    lines.extend(["", "[pipeline]"])
    if cfg.enrichments:
        formatted = ", ".join(f'"{e}"' for e in cfg.enrichments)
        lines.append(f"enrichments = [{formatted}]")
    else:
        lines.append("enrichments = []")

    lines.extend(["", "[llm]", f'provider = "{cfg.llm_provider}"'])

    lines.extend(["", "[observability]",
                  f"langfuse_enabled = {str(cfg.langfuse_enabled).lower()}"])

    lines.extend(["", "[sandbox]",
                  f"unsafe_python_sandbox = {str(cfg.unsafe_python_sandbox).lower()}"])

    return "\n".join(lines) + "\n"


def _render_env(cfg: EchoConfig) -> str:
    """Serialize secrets to .env format (KEY=value per line)."""
    pairs: list[tuple[str, str | None]] = [
        ("YOUTUBE_API_KEY",        cfg.api_keys.youtube),
        ("OPENAI_API_KEY",         cfg.api_keys.openai),
        ("OPENROUTER_API_KEY",     cfg.api_keys.openrouter),
        ("ANTHROPIC_API_KEY",      cfg.api_keys.anthropic),
        ("SPOTIFY_CLIENT_ID",      cfg.api_keys.spotify_client_id),
        ("SPOTIFY_CLIENT_SECRET",  cfg.api_keys.spotify_client_secret),
        ("LASTFM_API_KEY",         cfg.api_keys.lastfm),
        ("LANGFUSE_PUBLIC_KEY",    cfg.api_keys.langfuse_public),
        ("LANGFUSE_SECRET_KEY",    cfg.api_keys.langfuse_secret),
    ]
    lines = [
        "# Echo secrets. Generated by `echo init`. Never commit this file.",
        "# Empty values are omitted - add or edit them here freely.",
        "",
    ]
    for key, value in pairs:
        if value:
            lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"
