"""EchoConfig — single source of truth for runtime configuration.

Loaded from a TOML file (default: ~/.echo/config.toml) with API key secrets
merged from a .env file at the same location. Environment variables override
both. Used by every pipeline module and every CLI subcommand.

Schema layered to match the packaging design doc:
  - paths to raw data archives (Takeout, Spotify)
  - data directory (where echo.db / lancedb live)
  - which enrichment steps are enabled (YouTube API, Spotify API)
  - API keys for LLM providers and external services
  - LLM provider preference (anthropic / openai / openrouter)
  - observability toggles (Langfuse)

The default config is a "do nothing" config — empty Takeout paths, no
enrichments, no API keys. `echo init` populates it interactively;
`load_config()` reads what's saved.

Layered resolution (highest priority first):
  1. Explicit environment variables (OPENAI_API_KEY, ANTHROPIC_API_KEY, ...)
  2. ~/.echo/.env (secret values, never committed to git)
  3. ~/.echo/config.toml (non-secret preferences)
  4. Built-in defaults
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal

from echo.data.paths import (
    get_config_path,
    get_data_dir,
    get_env_path,
)

# ── Provider + enrichment enums ─────────────────────────────────────────────

LLMProvider = Literal["anthropic", "openai", "openrouter"]
Enrichment = Literal["youtube", "spotify"]

# Every env var the pipeline + agent might read. Used by load_config() to
# merge .env into the in-memory config. Keep in sync with .env.example.
_KNOWN_ENV_KEYS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "YOUTUBE_API_KEY",
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
    "SPOTIFY_ZIP",
    "LASTFM_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_HOST",
    "UNSAFE_PYTHON_SANDBOX",
    "VITE_API_URL",
)


# ── Sub-configs ─────────────────────────────────────────────────────────────


@dataclass
class TakeoutPaths:
    """Filesystem paths to the four raw archive sources.

    Each is optional - missing inputs produce a skipped-step message in the
    relevant pipeline module rather than an error.
    """
    youtube_zip: Path | None = None          # Google Takeout YouTube history
    activity_zip: Path | None = None         # Google My Activity export
    calendar_zip: Path | None = None         # Google Takeout Calendar export
    spotify_zip: Path | None = None          # Spotify Extended Streaming History


@dataclass
class APIKeys:
    """All third-party API keys.

    None means "not configured"; callers should handle gracefully (skip step,
    fall back to a different provider, or surface a clear setup error).
    """
    youtube: str | None = None               # YOUTUBE_API_KEY (enrich.py)
    openai: str | None = None                # OPENAI_API_KEY (reflect, embed, llm fallback)
    openrouter: str | None = None            # OPENROUTER_API_KEY (alt path for OpenAI calls)
    anthropic: str | None = None             # ANTHROPIC_API_KEY (Echo Speaks primary)
    spotify_client_id: str | None = None     # SPOTIFY_CLIENT_ID (enrich_spotify.py)
    spotify_client_secret: str | None = None # SPOTIFY_CLIENT_SECRET (enrich_spotify.py)
    lastfm: str | None = None                # LASTFM_API_KEY (enrich_music_meta.py)
    langfuse_public: str | None = None       # LANGFUSE_PUBLIC_KEY (observability)
    langfuse_secret: str | None = None       # LANGFUSE_SECRET_KEY (observability)


# ── Root config ─────────────────────────────────────────────────────────────


@dataclass
class EchoConfig:
    """Top-level runtime config.

    Build via `load_config()` (reads disk + env) or instantiate directly for
    tests. Passed by reference into every `pipeline.<step>.run(config)`.
    """

    # Where echo.db, lancedb/, config.toml, .env, private/ live.
    data_dir: Path = field(default_factory=get_data_dir)

    # Raw source archives.
    takeout: TakeoutPaths = field(default_factory=TakeoutPaths)

    # Which enrichment steps are enabled. Pipeline step skips itself if not in
    # this list - safe defaults for users without API keys.
    enrichments: list[Enrichment] = field(default_factory=list)

    # API keys (merged from .env + os.environ at load time).
    api_keys: APIKeys = field(default_factory=APIKeys)

    # Which LLM the agent + reflections prefer.
    llm_provider: LLMProvider = "anthropic"

    # Langfuse tracing on/off. If on but keys absent, observability degrades
    # to noop without erroring.
    langfuse_enabled: bool = False

    # Echo Speaks execute_python sandbox gate. "true" string in .env enables;
    # default false means execute_python returns a permission error string.
    unsafe_python_sandbox: bool = False

    # UI dev server proxy override (only used when running `npm run dev` from ui/).
    vite_api_url: str | None = None

    # ── Convenience accessors ──────────────────────────────────────────────

    @property
    def db_path(self) -> Path:
        """Resolved path to echo.db (data_dir / 'echo.db')."""
        return self.data_dir / "echo.db"

    @property
    def lancedb_path(self) -> Path:
        """Resolved path to lancedb/ vector store."""
        return self.data_dir / "lancedb"

    @property
    def private_dir(self) -> Path:
        """Resolved path to private/ (per-user life context annotations)."""
        return self.data_dir / "private"

    @property
    def annotations_path(self) -> Path:
        """Resolved path to private/annotations.yaml."""
        return self.private_dir / "annotations.yaml"

    def to_dict(self) -> dict:
        """Serialize for debugging. Path objects -> strings; secrets MASKED."""
        d = asdict(self)
        # Mask secret values for safe logging
        if d.get("api_keys"):
            for key, value in d["api_keys"].items():
                if value:
                    d["api_keys"][key] = f"***{value[-4:]}" if len(value) > 4 else "***"
        # Path -> str
        d["data_dir"] = str(self.data_dir)
        if d.get("takeout"):
            for key, value in d["takeout"].items():
                d["takeout"][key] = str(value) if value else None
        return d


# ── Loaders ─────────────────────────────────────────────────────────────────


def _parse_dotenv(path: Path) -> dict[str, str]:
    """Parse a .env file into a {KEY: value} dict.

    Minimal parser: skips comments and blank lines, splits on first '='.
    Does NOT interpolate ${VAR} references (none of Echo's env values use them).
    Returns {} if the file doesn't exist - allows callers to use setdefault
    semantics naturally.
    """
    if not path.exists():
        return {}
    parsed: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        parsed[key.strip()] = value.strip()
    return parsed


def _resolve_path(raw: str | None, *, base: Path) -> Path | None:
    """Resolve a config path string. Relative paths are relative to data_dir."""
    if not raw:
        return None
    p = Path(os.path.expandvars(raw)).expanduser()
    if not p.is_absolute():
        p = base / p
    return p


def load_config(
    config_path: Path | None = None,
    env_path: Path | None = None,
    data_dir: Path | None = None,
) -> EchoConfig:
    """Load config from disk + env into an EchoConfig.

    Resolution order (highest priority first):
      1. os.environ (set by shell / launching process)
      2. ~/.echo/.env (or env_path arg)
      3. ~/.echo/config.toml (or config_path arg)
      4. Built-in defaults from EchoConfig dataclass

    Missing files are silently ignored - this lets a fresh install with
    nothing configured return a default EchoConfig without erroring.

    Args:
        config_path: Override the TOML location (default: ~/.echo/config.toml)
        env_path:    Override the .env location (default: ~/.echo/.env)
        data_dir:    Override the data directory (default: $ECHO_DATA_DIR or ~/.echo)
    """
    resolved_data_dir = data_dir if data_dir is not None else get_data_dir()
    resolved_config_path = config_path if config_path is not None else get_config_path()
    resolved_env_path = env_path if env_path is not None else get_env_path()

    # Start with defaults
    cfg = EchoConfig(data_dir=resolved_data_dir)

    # Layer 1: TOML preferences
    if resolved_config_path.exists():
        try:
            toml_data = tomllib.loads(resolved_config_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise RuntimeError(
                f"Failed to parse {resolved_config_path}: {e}\n"
                f"Hint: run `echo init` to regenerate a valid config."
            ) from e
        _apply_toml(cfg, toml_data)

    # Layer 2 + 3: .env secrets then os.environ overrides
    env_values = _parse_dotenv(resolved_env_path)
    for key in _KNOWN_ENV_KEYS:
        # os.environ wins over .env (lets shell-set vars override the file)
        value = os.environ.get(key) or env_values.get(key)
        if value:
            _apply_env_value(cfg, key, value)

    return cfg


def _apply_toml(cfg: EchoConfig, data: dict) -> None:
    """Merge a parsed TOML dict into an EchoConfig in place."""
    # [takeout] section
    if (t := data.get("takeout")):
        cfg.takeout.youtube_zip  = _resolve_path(t.get("youtube_zip"),  base=cfg.data_dir)
        cfg.takeout.activity_zip = _resolve_path(t.get("activity_zip"), base=cfg.data_dir)
        cfg.takeout.calendar_zip = _resolve_path(t.get("calendar_zip"), base=cfg.data_dir)
        cfg.takeout.spotify_zip  = _resolve_path(t.get("spotify_zip"),  base=cfg.data_dir)

    # [pipeline] section
    if (p := data.get("pipeline")):
        if "enrichments" in p:
            cfg.enrichments = list(p["enrichments"])

    # [llm] section
    if (l := data.get("llm")):
        if (provider := l.get("provider")):
            cfg.llm_provider = provider

    # [observability] section
    if (o := data.get("observability")):
        cfg.langfuse_enabled = bool(o.get("langfuse_enabled", False))

    # [sandbox] section
    if (s := data.get("sandbox")):
        cfg.unsafe_python_sandbox = bool(s.get("unsafe_python_sandbox", False))


def _apply_env_value(cfg: EchoConfig, key: str, value: str) -> None:
    """Apply one env var to an EchoConfig in place."""
    match key:
        case "YOUTUBE_API_KEY":        cfg.api_keys.youtube = value
        case "OPENAI_API_KEY":         cfg.api_keys.openai = value
        case "OPENROUTER_API_KEY":     cfg.api_keys.openrouter = value
        case "ANTHROPIC_API_KEY":      cfg.api_keys.anthropic = value
        case "SPOTIFY_CLIENT_ID":      cfg.api_keys.spotify_client_id = value
        case "SPOTIFY_CLIENT_SECRET": cfg.api_keys.spotify_client_secret = value
        case "LASTFM_API_KEY":         cfg.api_keys.lastfm = value
        case "LANGFUSE_PUBLIC_KEY":    cfg.api_keys.langfuse_public = value
        case "LANGFUSE_SECRET_KEY":    cfg.api_keys.langfuse_secret = value
        case "SPOTIFY_ZIP":
            # Special: env-only override for the Spotify zip filename inside data_dir
            if cfg.takeout.spotify_zip is None:
                cfg.takeout.spotify_zip = cfg.data_dir / value
        case "UNSAFE_PYTHON_SANDBOX":
            cfg.unsafe_python_sandbox = value.strip().lower() == "true"
        case "VITE_API_URL":
            cfg.vite_api_url = value
        # LANGFUSE_HOST not stored on EchoConfig - api/observability.py reads it
        # from os.environ directly. Including in _KNOWN_ENV_KEYS still pushes it
        # into the process env, which is all that's needed.
        case _:
            pass


# ── Backward-compat shim for api/ during the migration window ──────────────


def load_env() -> None:
    """Legacy: read project-root .env into os.environ.

    Kept for api/ modules that still `from embed_common import load_env` and
    that haven't been migrated to EchoConfig yet. Removed at the end of the
    api/ migration step (P2.X).
    """
    legacy_env = Path.cwd() / ".env"
    if not legacy_env.exists():
        return
    for key, value in _parse_dotenv(legacy_env).items():
        os.environ.setdefault(key, value)


def get_embed_client(config: "EchoConfig | None" = None):
    """Returns (openai_client, model_name) preferring OPENAI_API_KEY.

    Resolution order:
      1. EchoConfig.api_keys (if config passed; this is the modern path that
         reads ~/.echo/.env via load_config())
      2. os.environ (legacy path for callers that pre-populated env)

    The legacy os.environ path is preserved for api/ modules that still
    call load_env() into the process env before invoking us.
    """
    try:
        import openai
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")

    openai_key: str | None = None
    openrouter_key: str | None = None
    if config is not None:
        openai_key = config.api_keys.openai
        openrouter_key = config.api_keys.openrouter
    openai_key = openai_key or os.environ.get("OPENAI_API_KEY")
    openrouter_key = openrouter_key or os.environ.get("OPENROUTER_API_KEY")

    if openai_key:
        return openai.OpenAI(api_key=openai_key), "text-embedding-3-small"

    if openrouter_key:
        return openai.OpenAI(api_key=openrouter_key, base_url="https://openrouter.ai/api/v1"), "openai/text-embedding-3-small"

    raise RuntimeError(
        "No embedding API key found. Add OPENAI_API_KEY or OPENROUTER_API_KEY to ~/.echo/.env."
    )


# Legacy: api/vec.py imports this list to know which tables to expose.
# spotify_tracks (5th) lands per the Spotify rework design - it carries
# Last.fm-sourced mood/genre tags so the agent's vector_search can answer
# cross-modal queries ("when was I in a melancholy phase, and what was I
# watching?"). The agent's vector_search dispatch picks it up automatically
# once it's in ALL_TABLES.
ALL_TABLES = ["reflections", "videos", "searches", "google_searches", "spotify_tracks"]
