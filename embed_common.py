"""
Shared utilities for embed.py and Spotify enrichment.

Single source of truth for embedding provider selection, model names, and
the canonical ALL_TABLES list. Currently imported by:
  - embed.py            : full embedding pipeline + ALL_TABLES + get_embed_client
  - enrich_spotify.py   : load_env (DRY-up of the env-loading helper)

Provider priority: OPENAI_API_KEY (direct) -> OPENROUTER_API_KEY
(via OpenAI-compatible base_url). Model is text-embedding-3-small (1536
dims) in both cases — OpenRouter just prefixes the model name with
'openai/'.

load_env() is intentionally simple: parses .env line-by-line into
os.environ.setdefault, so it never overrides values already set by the
shell. Drop-in alternative to python-dotenv for scripts that already
import this module.
"""

import os
import sys
from pathlib import Path

ENV_PATH = Path(__file__).parent / ".env"

OPENAI_EMBED_MODEL      = "text-embedding-3-small"
OPENROUTER_EMBED_MODEL  = "openai/text-embedding-3-small"

ALL_TABLES = ["reflections", "videos", "searches", "google_searches"]


def load_env():
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def get_embed_client():
    """Return (client, model_name). Prefers OPENAI_API_KEY; falls back to OPENROUTER_API_KEY."""
    try:
        import openai
    except ImportError:
        print("ERROR: openai package not installed. Run: pip install openai")
        sys.exit(1)

    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        return openai.OpenAI(api_key=key), OPENAI_EMBED_MODEL

    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    if or_key:
        return openai.OpenAI(
            api_key=or_key,
            base_url="https://openrouter.ai/api/v1",
        ), OPENROUTER_EMBED_MODEL

    print(
        "ERROR: No API key found.\n"
        "Add one of these to .env:\n"
        "  OPENAI_API_KEY=sk-...        (direct OpenAI)\n"
        "  OPENROUTER_API_KEY=sk-or-... (OpenRouter)"
    )
    sys.exit(1)
