"""Optional Langfuse observability for Echo Speaks (Langfuse SDK v4.x).

Usage in speak.py:
    lf    = get_langfuse()
    trace = lf.trace(query=req.query)
    gen   = trace.generation(round_n, model, history_len)
    gen.done(raw_response)
    span  = trace.tool(tool_name, args, round_n)
    span.done(observation, source_tag)
    trace.finish(findings_count, rounds_used, hit_limit)
    lf.flush()

If Langfuse keys are not in .env, every call is a silent no-op.
"""

from __future__ import annotations
import os


# ── No-op stubs ────────────────────────────────────────────────────────────────

class _NoopPrompt:
    """Fallback prompt client when Langfuse is unavailable."""
    def __init__(self, text: str):
        self._text = text

    def compile(self, **kwargs: str) -> str:
        result = self._text
        for k, v in kwargs.items():
            result = result.replace("{{" + k + "}}", str(v))
        return result


class _NoopSpan:
    def done(self, *_, **__): pass


class _NoopTrace:
    def generation(self, *_, **__): return _NoopSpan()
    def tool(self, *_, **__):       return _NoopSpan()
    def finish(self, *_, **__):     pass
    @property
    def trace_id(self) -> str:      return ""


class _NoopLangfuse:
    def trace(self, **__):                         return _NoopTrace()
    def score(self, trace_id: str = "", name: str = "", value: float = 0.0, comment: str | None = None): pass
    def seed_prompt(self, *_, **__):               pass
    def get_prompt(self, name: str, fallback: str) -> _NoopPrompt:
        return _NoopPrompt(fallback)
    def flush(self):                               pass


# ── Live wrappers ──────────────────────────────────────────────────────────────

class _LiveSpan:
    def __init__(self, obs):
        self._obs = obs

    def done(self, output, **meta):
        try:
            usage = meta.pop("usage", None)
            model = meta.pop("model", None)
            update_kwargs: dict = {"output": output}
            if usage:
                # Langfuse 4.x usage_details keys. We pass both Anthropic's native
                # field names and Langfuse's canonical short names — Langfuse's
                # Claude model definitions map either form for cost calc.
                # input_tokens from Anthropic excludes cache reads/writes already,
                # so the four fields together describe the full bill correctly.
                usage_details: dict = {
                    "input":  usage.get("input_tokens", 0),
                    "output": usage.get("output_tokens", 0),
                }
                cache_read     = usage.get("cache_read_input_tokens", 0)
                cache_creation = usage.get("cache_creation_input_tokens", 0)
                if cache_read:
                    usage_details["cache_read_input_tokens"] = cache_read
                if cache_creation:
                    usage_details["cache_creation_input_tokens"] = cache_creation
                update_kwargs["usage_details"] = usage_details
            if model:
                update_kwargs["model"] = model
            if meta:
                update_kwargs["metadata"] = meta
            self._obs.update(**update_kwargs)
            self._obs.end()
        except Exception:
            pass


class _LiveTrace:
    def __init__(self, root):
        self._root = root

    def generation(self, round_n: int, model: str, history_len: int) -> _LiveSpan:
        try:
            obs = self._root.start_observation(
                name=f"round-{round_n}",
                as_type="generation",
                model=model,
                metadata={"round": round_n, "history_len": history_len},
            )
            return _LiveSpan(obs)
        except Exception:
            return _LiveSpan(None)  # type: ignore

    def tool(self, tool_name: str, args: dict, round_n: int) -> _LiveSpan:
        try:
            obs = self._root.start_observation(
                name=f"tool-{tool_name}",
                as_type="tool",
                input={k: str(v)[:200] for k, v in args.items()},
                metadata={"round": round_n},
            )
            return _LiveSpan(obs)
        except Exception:
            return _LiveSpan(None)  # type: ignore

    def finish(self, findings_count: int, rounds_used: int, hit_limit: bool):
        try:
            self._root.update(output={
                "findings_count": findings_count,
                "rounds_used": rounds_used,
                "hit_limit": hit_limit,
            })
            self._root.end()
        except Exception:
            pass

    @property
    def trace_id(self) -> str:
        try:
            return str(self._root.trace_id)
        except Exception:
            return ""


class _LiveLangfuse:
    def __init__(self, client):
        self._client = client

    def trace(self, **kwargs) -> _LiveTrace:
        try:
            root = self._client.start_observation(
                name="echo-speaks",
                as_type="agent",
                input=kwargs,
            )
            return _LiveTrace(root)
        except Exception:
            return _NoopTrace()  # type: ignore

    def score(self, trace_id: str, name: str, value: float, comment: str | None = None) -> None:
        try:
            kwargs: dict = {"trace_id": trace_id, "name": name, "value": value}
            if comment is not None:
                kwargs["comment"] = comment
            self._client.score(**kwargs)
        except Exception:
            pass

    def seed_prompt(self, name: str, template: str) -> None:
        """Push the prompt template to Langfuse if it doesn't already exist."""
        try:
            self._client.get_prompt(name, fetch_timeout_seconds=3)
            # Already exists — leave it alone so dashboard edits are preserved
        except Exception:
            try:
                self._client.create_prompt(
                    name=name,
                    prompt=template,
                    labels=["production"],
                    commit_message="Auto-seeded by Echo Speaks on first startup",
                )
                print(f"[observability] Seeded prompt '{name}' to Langfuse")
            except Exception as e:
                print(f"[observability] Could not seed prompt '{name}': {e}")

    def get_prompt(self, name: str, fallback: str) -> object:
        try:
            return self._client.get_prompt(
                name,
                type="text",
                label="production",
                fallback=fallback,
                cache_ttl_seconds=300,   # 5-min cache; dashboard changes land within 5 min
            )
        except Exception:
            return _NoopPrompt(fallback)

    def flush(self):
        try:
            self._client.flush()
        except Exception:
            pass


# ── Factory ────────────────────────────────────────────────────────────────────

_instance = None
_init_tried = False


def get_langfuse() -> _LiveLangfuse | _NoopLangfuse:
    """Return a live Langfuse wrapper or a no-op stub."""
    global _instance, _init_tried
    if _init_tried:
        return _instance  # type: ignore

    _init_tried = True
    from echo.config import load_env
    load_env()

    pk = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    sk = os.environ.get("LANGFUSE_SECRET_KEY", "")
    if not pk or not sk:
        _instance = _NoopLangfuse()
        return _instance

    try:
        from langfuse import Langfuse
        host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
        client = Langfuse(public_key=pk, secret_key=sk, host=host)
        client.auth_check()
        _instance = _LiveLangfuse(client)
        print(f"[observability] Langfuse connected: {host}")
    except ImportError:
        print("[observability] langfuse package not installed -- run: pip install langfuse")
        _instance = _NoopLangfuse()
    except Exception as e:
        print(f"[observability] Langfuse init failed: {e}")
        _instance = _NoopLangfuse()

    return _instance  # type: ignore
