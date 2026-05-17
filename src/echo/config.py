"""EchoConfig — single source of truth for runtime configuration.

Populated in Step P2.4 of the packaging session. This stub satisfies the
package import graph so the skeleton is loadable end-to-end.

The final shape (per the packaging design doc) is:

    @dataclass
    class EchoConfig:
        takeout_paths: dict[str, Path]          # YouTube / activity / calendar zip paths
        spotify_zip: Path | None
        data_dir: Path                          # default ~/.echo/
        enrichments: list[Literal["youtube", "spotify"]]
        api_keys: dict[str, str | None]         # YOUTUBE_API_KEY, OPENAI_API_KEY, ...
        llm_provider: Literal["anthropic", "openai", "openrouter"]
        langfuse_enabled: bool

with load_config() reading ~/.echo/config.toml and merging secrets from .env.
"""

from dataclasses import dataclass, field
from pathlib import Path

from echo.data.paths import get_data_dir


@dataclass
class EchoConfig:
    """Placeholder config. Filled out in Step P2.4."""
    data_dir: Path = field(default_factory=get_data_dir)


def load_config() -> EchoConfig:
    """Placeholder loader. Returns a default-valued EchoConfig."""
    return EchoConfig()


# Backward-compat helper for the legacy `from embed_common import load_env` callsites
# in api/. Replaced by EchoConfig wiring during the api/ migration step.
def load_env() -> None:
    """Read the project-root .env into os.environ (setdefault semantics).

    Honors the existing .env layout while we transition to config-driven secrets.
    """
    import os

    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())
