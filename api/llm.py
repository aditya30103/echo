"""LLM provider routing for the Echo API.

Priority order:
  1. ANTHROPIC_API_KEY  → native Anthropic SDK  (Claude Sonnet 4.6)
  2. OPENAI_API_KEY     → OpenAI SDK            (GPT-4o)
  3. OPENROUTER_API_KEY → OpenAI-compat client  (routes to GPT-4o or Claude)

The chat() function is the single call-site for all LLM text generation.
"""

from __future__ import annotations
import os
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

CLAUDE_MODEL   = "claude-sonnet-4-6"
GPT4O_MODEL    = "openai/gpt-4o"          # OpenRouter slug
GPT4O_DIRECT   = "gpt-4o"                 # OpenAI direct slug


def _load_env():
    from embed_common import load_env
    load_env()


def available_models() -> list[str]:
    """Return which model IDs are usable given current .env keys."""
    _load_env()
    models = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        models.append("claude")
    if os.environ.get("OPENAI_API_KEY"):
        models.append("gpt4o")
    if os.environ.get("OPENROUTER_API_KEY"):
        if "claude" not in models:
            models.append("claude")   # via OpenRouter
        if "gpt4o" not in models:
            models.append("gpt4o")    # via OpenRouter
    return models or []


def chat(
    messages: list[dict],  # [{"role": "user"|"assistant"|"system", "content": str}]
    model: str = "auto",   # "auto" | "claude" | "gpt4o"
    max_tokens: int = 1024,
    temperature: float = 0.7,
) -> tuple[str, str]:
    """Call an LLM and return (text, model_label).

    model="auto" → prefers Claude if ANTHROPIC_API_KEY is set, else GPT-4o.
    """
    _load_env()

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    openai_key    = os.environ.get("OPENAI_API_KEY", "")
    or_key        = os.environ.get("OPENROUTER_API_KEY", "")

    want_claude = model in ("claude", "auto")
    want_gpt4o  = model == "gpt4o"

    # ── Claude path ─────────────────────────────────────────────────────
    if want_claude and anthropic_key:
        import anthropic as _anthropic
        client = _anthropic.Anthropic(api_key=anthropic_key)
        system_msgs = [m["content"] for m in messages if m["role"] == "system"]
        user_msgs   = [m for m in messages if m["role"] != "system"]
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=system_msgs[0] if system_msgs else "",
            messages=user_msgs,
            timeout=60,
        )
        return resp.content[0].text.strip(), f"claude-sonnet-4-6"

    # ── Claude via OpenRouter ────────────────────────────────────────────
    if want_claude and or_key and not want_gpt4o:
        import openai
        client = openai.OpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1")
        resp = client.chat.completions.create(
            model=f"anthropic/{CLAUDE_MODEL}",
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=60,
        )
        return resp.choices[0].message.content.strip(), f"claude-sonnet-4-6 (OpenRouter)"

    # ── GPT-4o direct ───────────────────────────────────────────────────
    if openai_key:
        import openai
        client = openai.OpenAI(api_key=openai_key)
        resp = client.chat.completions.create(
            model=GPT4O_DIRECT,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=60,
        )
        return resp.choices[0].message.content.strip(), "gpt-4o"

    # ── GPT-4o via OpenRouter ────────────────────────────────────────────
    if or_key:
        import openai
        client = openai.OpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1")
        resp = client.chat.completions.create(
            model=GPT4O_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=60,
        )
        return resp.choices[0].message.content.strip(), "gpt-4o (OpenRouter)"

    raise RuntimeError(
        "No LLM API key found. Add ANTHROPIC_API_KEY, OPENAI_API_KEY, "
        "or OPENROUTER_API_KEY to .env"
    )
