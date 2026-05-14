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

class _NoopSpan:
    def done(self, *_, **__): pass


class _NoopTrace:
    def generation(self, *_, **__): return _NoopSpan()
    def tool(self, *_, **__):       return _NoopSpan()
    def finish(self, *_, **__):     pass


class _NoopLangfuse:
    def trace(self, **__):  return _NoopTrace()
    def flush(self):        pass


# ── Live wrappers ──────────────────────────────────────────────────────────────

class _LiveSpan:
    def __init__(self, obs):
        self._obs = obs

    def done(self, output, **meta):
        try:
            self._obs.update(output=output, metadata=meta or None)
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
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from embed_common import load_env
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
