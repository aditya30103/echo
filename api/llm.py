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


def _inject_prefix(messages: list[dict], cached_prefix: str) -> list[dict]:
    """Prepend cached_prefix to the first system message for non-Anthropic paths.

    Anthropic handles prefix caching natively via two system blocks.
    All other providers receive the preamble concatenated into the system message.
    """
    result = []
    injected = False
    for m in messages:
        if m["role"] == "system" and not injected:
            result.append({"role": "system", "content": cached_prefix + "\n" + m["content"]})
            injected = True
        else:
            result.append(m)
    if not injected:
        result = [{"role": "system", "content": cached_prefix}] + result
    return result


def chat(
    messages: list[dict],          # [{"role": "user"|"assistant"|"system", "content": str}]
    model: str = "auto",           # "auto" | "claude" | "gpt4o"
    max_tokens: int = 1024,
    temperature: float = 0.7,
    cached_prefix: str | None = None,  # stable preamble to cache on Anthropic path
) -> tuple[str, str, dict, str]:
    """Call an LLM and return (text, model_label, usage, stop_reason).

    usage = {"input_tokens": int, "output_tokens": int,
             "cache_read_input_tokens": int, "cache_creation_input_tokens": int}
    stop_reason = "end_turn" | "max_tokens" | "stop" | "length" | "unknown"
    model="auto" → prefers Claude if ANTHROPIC_API_KEY is set, else GPT-4o.

    cached_prefix: when provided on the Anthropic native path, the prefix is sent
    as Block 1 with cache_control=ephemeral and the system message as Block 2.
    On all other paths the prefix is prepended to the system message text.
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

        if cached_prefix is not None and system_msgs:
            # Two cache checkpoints:
            # Block 1 (preamble: schema + rubric) — stable across ALL rounds → hits from round 2.
            # Block 2 (instructions: phase rules + tools) — stable within each phase.
            #   Phase 1→2 transition writes a new Block 2 cache entry (one miss), then hits resume.
            system_param: str | list = [
                {"type": "text", "text": cached_prefix, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": system_msgs[0], "cache_control": {"type": "ephemeral"}},
            ]
        else:
            system_param = system_msgs[0] if system_msgs else ""

        # Use streaming to avoid the 60s non-streaming timeout for long outputs.
        # At round 40-50 the finish call can generate 2000-4000 tokens; streaming
        # keeps the connection alive as tokens flow — no wall-clock timeout applies.
        with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=system_param,
            messages=user_msgs,
        ) as stream:
            resp = stream.get_final_message()
        usage = {
            "input_tokens":                resp.usage.input_tokens,
            "output_tokens":               resp.usage.output_tokens,
            "cache_read_input_tokens":     getattr(resp.usage, "cache_read_input_tokens", 0),
            "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0),
        }
        return resp.content[0].text.strip(), "claude-sonnet-4-6", usage, str(resp.stop_reason or "unknown")

    # ── Claude via OpenRouter ────────────────────────────────────────────
    if want_claude and or_key and not want_gpt4o:
        import openai
        client = openai.OpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1")
        msgs = _inject_prefix(messages, cached_prefix) if cached_prefix else messages
        resp = client.chat.completions.create(
            model=f"anthropic/{CLAUDE_MODEL}",
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=60,
        )
        usage = {"input_tokens": resp.usage.prompt_tokens, "output_tokens": resp.usage.completion_tokens,
                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        return resp.choices[0].message.content.strip(), "claude-sonnet-4-6 (OpenRouter)", usage, str(resp.choices[0].finish_reason or "unknown")

    # ── GPT-4o direct ───────────────────────────────────────────────────
    if openai_key:
        import openai
        client = openai.OpenAI(api_key=openai_key)
        msgs = _inject_prefix(messages, cached_prefix) if cached_prefix else messages
        resp = client.chat.completions.create(
            model=GPT4O_DIRECT,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=60,
        )
        usage = {"input_tokens": resp.usage.prompt_tokens, "output_tokens": resp.usage.completion_tokens,
                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        return resp.choices[0].message.content.strip(), "gpt-4o", usage, str(resp.choices[0].finish_reason or "unknown")

    # ── GPT-4o via OpenRouter ────────────────────────────────────────────
    if or_key:
        import openai
        client = openai.OpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1")
        msgs = _inject_prefix(messages, cached_prefix) if cached_prefix else messages
        resp = client.chat.completions.create(
            model=GPT4O_MODEL,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=60,
        )
        usage = {"input_tokens": resp.usage.prompt_tokens, "output_tokens": resp.usage.completion_tokens,
                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        return resp.choices[0].message.content.strip(), "gpt-4o (OpenRouter)", usage, str(resp.choices[0].finish_reason or "unknown")

    raise RuntimeError(
        "No LLM API key found. Add ANTHROPIC_API_KEY, OPENAI_API_KEY, "
        "or OPENROUTER_API_KEY to .env"
    )
