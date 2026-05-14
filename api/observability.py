"""Optional Langfuse observability for Echo Speaks.

If LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not in .env, every call
returns a no-op stub and tracing is completely transparent to the caller.
"""

from __future__ import annotations
import os


class _NoopTrace:
    """Drop-in stub when Langfuse is not configured."""
    def generation(self, **_): return self
    def span(self, **_): return self
    def event(self, **_): return self
    def update(self, **_): pass
    def end(self, **_): pass


class _NoopLangfuse:
    def trace(self, **_): return _NoopTrace()
    def flush(self): pass


_client = None
_init_tried = False


def get_langfuse():
    """Return a live Langfuse client or a no-op stub."""
    global _client, _init_tried
    if _init_tried:
        return _client

    _init_tried = True
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from embed_common import load_env
    load_env()

    pk = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    sk = os.environ.get("LANGFUSE_SECRET_KEY", "")
    if not pk or not sk:
        _client = _NoopLangfuse()
        return _client

    try:
        from langfuse import Langfuse
        host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
        _client = Langfuse(public_key=pk, secret_key=sk, host=host)
        print(f"[observability] Langfuse connected → {host}")
    except ImportError:
        print("[observability] langfuse package not installed — run: pip install langfuse")
        _client = _NoopLangfuse()
    except Exception as e:
        print(f"[observability] Langfuse init failed: {e}")
        _client = _NoopLangfuse()

    return _client
