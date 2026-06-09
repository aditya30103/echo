"""LLM provider routing for the Echo API.

Priority order (for model="auto"):
  1. ANTHROPIC_API_KEY  → native Anthropic SDK  (Claude Sonnet 4.6)
  2. OPENAI_API_KEY     → OpenAI SDK            (GPT-4o)
  3. OPENROUTER_API_KEY → OpenAI-compat client  (routes to GPT-4o or Claude)
  4. OLLAMA_BASE_URL    → local OpenAI-compat   (no API key needed; last fallback)

Ollama is the only no-cloud-key path: `auto` falls back to it only when no cloud
key is set, so a user with zero API keys can still run Echo locally. `model="ollama"`
forces it explicitly even when cloud keys exist. It is never auto-preferred over a
cloud key — local models are weaker on the multi-step Speaks ReAct loop.

The chat() function is the single call-site for all LLM text generation.
"""

from __future__ import annotations
import os

CLAUDE_MODEL   = "claude-sonnet-4-6"
GPT4O_MODEL    = "openai/gpt-4o"          # OpenRouter slug
GPT4O_DIRECT   = "gpt-4o"                 # OpenAI direct slug

# Default local model. llama3.1 ships a 128k context window — the Speaks agent
# concatenates a large schema/rubric prefix and runs 20-50 rounds, so a short-ctx
# default (e.g. an 8k model) would overflow mid-run. Override with OLLAMA_MODEL.
DEFAULT_OLLAMA_MODEL = "llama3.1"
# Local inference is slow (CPU token rates), so a 50-round finish call can take
# minutes. This timeout is finite ONLY to avoid an infinite hang when OLLAMA_BASE_URL
# points at a server that is down or unresponsive — it is not a performance budget.
OLLAMA_TIMEOUT = 300

_OLLAMA_WARNED = False  # module-level: warn once per process when the local path is taken


def _load_env():
    from echo.config import load_env
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
    if os.environ.get("OLLAMA_BASE_URL"):
        # Env-var presence only — we do not ping the server here (a reachability
        # check is deferred; see TODOS.md). Listed last: local is the fallback tier.
        models.append("ollama")
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


def _openai_compat_chat(
    *,
    base_url: str | None,   # None → OpenAI's default endpoint
    api_key: str,
    model_slug: str,
    label: str,             # human-readable model label returned to callers
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    cached_prefix: str | None,
    timeout: float = 60,
) -> tuple[str, str, dict, str]:
    """Shared OpenAI-compatible chat call — OpenRouter, OpenAI direct, and Ollama.

    These three providers differ only in base_url, api_key, model slug, and the
    label they report; the request/response handling is identical. The Anthropic
    native path is deliberately NOT routed here — it uses two-block prefix caching
    and a streaming context manager that this shared path doesn't model.

    `timeout` is mandatory and has no "off" value on purpose: a local Ollama server
    that is configured (OLLAMA_BASE_URL set) but not running would otherwise hang
    the request forever with no error. A finite timeout turns that into a clean
    failure the caller can surface.
    """
    import openai
    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    msgs = _inject_prefix(messages, cached_prefix) if cached_prefix else messages
    resp = client.chat.completions.create(
        model=model_slug,
        messages=msgs,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    )
    usage = {
        "input_tokens":                resp.usage.prompt_tokens,
        "output_tokens":               resp.usage.completion_tokens,
        "cache_read_input_tokens":     0,
        "cache_creation_input_tokens": 0,
    }
    return (
        resp.choices[0].message.content.strip(),
        label,
        usage,
        str(resp.choices[0].finish_reason or "unknown"),
    )


def _ollama_chat(
    messages: list[dict],
    base_url: str,
    model_name: str,
    max_tokens: int,
    temperature: float,
    cached_prefix: str | None,
) -> tuple[str, str, dict, str]:
    """Route to a local Ollama server via its OpenAI-compatible endpoint.

    Warns once per process about the context-window caveat: the Speaks agent runs
    20-50 rounds with a large concatenated prefix and will overflow a short-context
    local model. Chat and simple queries are fine on smaller models.
    """
    global _OLLAMA_WARNED
    if not _OLLAMA_WARNED:
        import logging
        logging.getLogger("echo.llm").warning(
            "Routing to local Ollama (model=%s). The Echo Speaks agent runs 20-50 "
            "rounds and concatenates a large schema/rubric prefix — use a long-context "
            "model (set OLLAMA_MODEL) or it will overflow mid-run. Chat and simple "
            "queries work well on smaller models.",
            model_name,
        )
        _OLLAMA_WARNED = True

    # Ollama's OpenAI-compatible API lives at {base}/v1. Accept the base with or
    # without the suffix so OLLAMA_BASE_URL=http://localhost:11434 also works.
    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"

    return _openai_compat_chat(
        base_url=base,
        api_key="ollama",          # Ollama ignores the key, but the SDK requires a non-empty one
        model_slug=model_name,
        label=f"ollama:{model_name}",
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        cached_prefix=cached_prefix,
        timeout=OLLAMA_TIMEOUT,    # finite: avoids an infinite hang on a down server
    )


def chat(
    messages: list[dict],          # [{"role": "user"|"assistant"|"system", "content": str}]
    model: str = "auto",           # "auto" | "claude" | "gpt4o" | "ollama"
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
    ollama_base   = os.environ.get("OLLAMA_BASE_URL", "")
    ollama_model  = os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)

    want_claude = model in ("claude", "auto")
    want_gpt4o  = model == "gpt4o"
    want_ollama = model == "ollama"

    # ── Explicit local select ───────────────────────────────────────────
    # Handle model="ollama" up front so we never silently fall through to a cloud
    # key the user didn't ask for. If they asked for local but didn't configure it,
    # that's a clear error, not a surprise cloud bill.
    if want_ollama:
        if ollama_base:
            return _ollama_chat(messages, ollama_base, ollama_model,
                                 max_tokens, temperature, cached_prefix)
        raise RuntimeError(
            "model='ollama' was requested but OLLAMA_BASE_URL is not set in .env "
            "(e.g. OLLAMA_BASE_URL=http://localhost:11434)"
        )

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
        return _openai_compat_chat(
            base_url="https://openrouter.ai/api/v1", api_key=or_key,
            model_slug=f"anthropic/{CLAUDE_MODEL}", label="claude-sonnet-4-6 (OpenRouter)",
            messages=messages, max_tokens=max_tokens, temperature=temperature,
            cached_prefix=cached_prefix,
        )

    # ── GPT-4o direct ───────────────────────────────────────────────────
    if openai_key:
        return _openai_compat_chat(
            base_url=None, api_key=openai_key,
            model_slug=GPT4O_DIRECT, label="gpt-4o",
            messages=messages, max_tokens=max_tokens, temperature=temperature,
            cached_prefix=cached_prefix,
        )

    # ── GPT-4o via OpenRouter ────────────────────────────────────────────
    if or_key:
        return _openai_compat_chat(
            base_url="https://openrouter.ai/api/v1", api_key=or_key,
            model_slug=GPT4O_MODEL, label="gpt-4o (OpenRouter)",
            messages=messages, max_tokens=max_tokens, temperature=temperature,
            cached_prefix=cached_prefix,
        )

    # ── Ollama fallback ─────────────────────────────────────────────────
    # Last resort for model="auto"/"claude" when NO cloud key is set: a user with
    # zero API keys still gets local inference instead of a hard error. This is the
    # "no API key needed" adoption path. Cloud keys, if present, always win above.
    if ollama_base:
        return _ollama_chat(messages, ollama_base, ollama_model,
                            max_tokens, temperature, cached_prefix)

    raise RuntimeError(
        "No LLM provider configured. Add ANTHROPIC_API_KEY, OPENAI_API_KEY, "
        "OPENROUTER_API_KEY, or OLLAMA_BASE_URL to .env"
    )
