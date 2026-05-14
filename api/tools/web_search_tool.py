"""web_search tool — DuckDuckGo search for event cross-referencing."""

_RATE_LIMIT = 5  # max calls per ReAct loop session


def run_web_search(query: str, k: int = 3, session_state: dict | None = None) -> str:
    """Search the web via DuckDuckGo. Rate-limited to 5 calls per session.

    Returns [EXTERNAL] tagged string with title + snippet + URL per result.
    Empty results explicitly flag possible DDG rate limiting vs. genuine no-results.
    """
    if session_state is None:
        session_state = {}

    count = session_state.get("web_search_count", 0)
    if count >= _RATE_LIMIT:
        return (
            f"[EXTERNAL] BLOCKED: web_search limit reached ({_RATE_LIMIT} calls/session). "
            "Use the data already in context to finish your analysis."
        )

    try:
        from duckduckgo_search import DDGS
        results = list(DDGS().text(query, max_results=k))
    except ImportError:
        return "[EXTERNAL] ERROR: duckduckgo-search library not installed."
    except Exception as e:
        session_state["web_search_count"] = count + 1
        return f"[EXTERNAL] ERROR: {e}"

    session_state["web_search_count"] = count + 1

    if not results:
        return (
            "[EXTERNAL] web_search: no results returned — "
            "DDG may be rate-limiting this IP. Try a more specific query or use youtube_lookup instead."
        )

    lines = [f"[EXTERNAL] web_search: query={query!r} ({len(results)} results)"]
    for r in results:
        title   = r.get("title", "").strip()
        snippet = (r.get("body") or r.get("snippet") or "").strip()[:300]
        url     = r.get("href", "")
        lines.append(f"  - {title}\n    {snippet}\n    URL: {url}")

    return "\n".join(lines)
