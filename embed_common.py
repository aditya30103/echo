"""
Shared utilities for embed.py and query.py.

Single source of truth for provider selection, model names, and table list.
"""

import os
import sys
from pathlib import Path

ENV_PATH = Path(__file__).parent / ".env"

OPENAI_EMBED_MODEL      = "text-embedding-3-small"
OPENROUTER_EMBED_MODEL  = "openai/text-embedding-3-small"

ALL_TABLES = ["reflections", "videos", "searches"]


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
