"""Per-tool observation compressors for Echo Speaks `_trim_history`.

Layer 1 of the context-management redesign. Replaces the dumb `[:200]` string
truncation in `_trim_history` with semantic per-tool compression that preserves
the key information an agent would want to recall from earlier rounds.

Design rationale: see D:/Projects/Echo/CONTEXT_MGMT_ANALYSIS.md.

Each compressor takes the BODY of an observation (after the `[TAG]` header is
stripped) and returns a short, semantically-rich summary. Target size: 300–600
chars per compressed observation. Compressors are pure, deterministic, and
infallible — any failure inside a compressor falls back to the first-N-chars
trim so `_trim_history` never raises.

Output envelope: `[<TAG>] (compressed)\n<body>`. The original `[TAG]` prefix is
preserved so `_source_tag()` and downstream Langfuse trace tagging keep working;
`(compressed)` signals to the agent that this is a summary, not the raw output.

The user OBSERVATION wrapper line (`OBSERVATION (round N/M, phase P):`) is kept
on top of the compressed body so the agent retains round-number context.
"""

from __future__ import annotations

import json
import re
from typing import Callable

# ── Constants ─────────────────────────────────────────────────────────────────

# Match a leading `[TAG]` prefix. Captures the tag name.
_TAG_RE = re.compile(r"^\[([A-Z-]+)\]")

# Match a column name inside a stringified dict row like `{'col': value, ...}`.
# Used by compress_sql to pull column names without ast.literal_eval (safer +
# handles non-literal values like datetime objects gracefully).
_DICT_KEY_RE = re.compile(r"'([^']+)':")

# Match the trailing "[N rows]" or "[N rows — may be more, hit row limit]" marker
# that sql_tool.py appends to every successful run_sql output.
_SQL_ROW_MARKER_RE = re.compile(r"^\[(\d+) rows( — may be more, hit row limit)?\]$")

# Match the OBSERVATION wrapper that _react_loop prepends to every user-role
# observation message: "OBSERVATION (round 5/50, phase 1):\n<body>".
_OBS_WRAPPER_RE = re.compile(r"^(OBSERVATION \([^)]+\):)\n(.*)$", re.DOTALL)

# Match assistant message THOUGHT and ACTION blocks (same regex shape as
# speak.py:_THOUGHT_RE / _ACTION_RE but recompiled here to avoid the import
# cycle).
_THOUGHT_RE = re.compile(r"THOUGHT:\s*(.*?)(?=ACTION:|$)", re.DOTALL)
_ACTION_RE  = re.compile(r'ACTION:\s*(\{.*\})', re.DOTALL)


# ── Per-tag compressors ──────────────────────────────────────────────────────

def compress_sql(body: str) -> str:
    """Compress a `[RAW-SQL]` body.

    Input shape (from sql_tool.py):
        {'col1': v, 'col2': v}
        {'col1': v, 'col2': v}
        ...
        [N rows]                                    (or "[N rows — may be more, hit row limit]")

    Output shape:
        cols: col1, col2, col3
        first: {'col1': v, 'col2': v, 'col3': v}
        last:  {'col1': v, 'col2': v, 'col3': v}
        [N rows]

    Short bodies (≤200 chars) and error/empty bodies pass through unchanged.
    """
    body = body.strip()
    if len(body) <= 200:
        return body

    # ERROR or "(no rows returned)" outputs are already concise — pass through.
    if body.startswith("ERROR:") or body.startswith("(no rows"):
        return body

    lines = body.splitlines()
    if len(lines) < 3:
        return body

    # Last line should be the "[N rows]" marker. If not, this body doesn't look
    # like a normal sql_tool result — fall back.
    marker_line = lines[-1].strip()
    if not _SQL_ROW_MARKER_RE.match(marker_line):
        return body

    data_lines = [ln for ln in lines[:-1] if ln.strip()]
    if len(data_lines) < 2:
        return body  # Only one data row — not worth compressing.

    first_line = data_lines[0]
    last_line  = data_lines[-1]

    cols = _DICT_KEY_RE.findall(first_line)
    cols_str = ", ".join(cols) if cols else "(unparseable)"

    return (
        f"cols: {cols_str}\n"
        f"first: {first_line}\n"
        f"last:  {last_line}\n"
        f"{marker_line}"
    )


def compress_python(body: str) -> str:
    """Compress a `[RAW-COMPUTED]` body (execute_python, run_pelt, run_clustering).

    Strategy: keep the first non-empty line (typically a section header from the
    agent's print()) plus the last ~250 chars (typically the conclusion or final
    summary). For ERROR bodies, expand the tail to 400 chars so the traceback
    contains useful context.

    Short bodies (≤300 chars) and empty/no-output bodies pass through unchanged.
    """
    body = body.strip()
    if len(body) <= 300:
        return body

    # Errors get more tail to preserve traceback context.
    is_error = body.startswith("ERROR:") or "ERROR:" in body[:500]
    tail_chars = 400 if is_error else 250

    lines = body.splitlines()
    first_nonempty = next((ln for ln in lines if ln.strip()), "")
    tail = body[-tail_chars:].lstrip()

    # If the head already contains the tail (short body that we shouldn't have
    # gotten this far on), just return the body.
    if first_nonempty in tail:
        return body

    return f"{first_nonempty}\n[... middle elided ...]\n{tail}"


def compress_vsearch(body: str) -> str:
    """Compress a `[SEMANTIC-RAW]` or `[NARRATIVE]` body.

    Input shape (from search_tool.py):
        table=videos
          [85%] Title — Channel (watched 3×)
          [80%] Title — Channel (watched 1×)
          ...

    Strategy: keep the `table=...` header line + first 3 result lines + count of
    remaining results. Short bodies (≤300 chars) pass through unchanged.
    """
    body = body.strip()
    if len(body) <= 300:
        return body

    lines = body.splitlines()
    header  = lines[0] if lines and lines[0].startswith("table=") else ""
    results = [ln for ln in lines[1:] if ln.strip().startswith("[")]

    if not results:
        return body

    kept = results[:3]
    remaining = len(results) - len(kept)
    suffix = f"\n  (+{remaining} more results)" if remaining > 0 else ""

    head = (header + "\n") if header else ""
    return head + "\n".join(kept) + suffix


def compress_external(body: str) -> str:
    """Compress an `[EXTERNAL]` body (youtube_lookup JSON or web_search lines).

    youtube_lookup format: pretty-printed JSON dict with title/channel/duration/views.
    web_search format: line-based "1. Title\\n   URL\\n   snippet".

    Short bodies (≤300 chars) pass through unchanged.
    """
    body = body.strip()
    if len(body) <= 300:
        return body

    # JSON path: youtube_lookup.
    if body.startswith("{"):
        try:
            data = json.loads(body)
            keep = {
                k: data[k] for k in ("title", "channel", "channel_title",
                                     "view_count", "duration", "category")
                if k in data
            }
            return json.dumps(keep, indent=2)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass  # Fall through to line-based path.

    # Line-based path: web_search. Keep first ~2 results worth of lines.
    lines = body.splitlines()
    # web_search emits 3-line blocks per result (title, url, snippet). Keep 6 lines.
    kept = lines[:6]
    remaining_blocks = max(0, (len(lines) - 6) // 3)
    suffix = f"\n  (+{remaining_blocks} more results)" if remaining_blocks > 0 else ""
    return "\n".join(kept) + suffix


def compress_narrative(body: str) -> str:
    """Compress a `[NARRATIVE]` body — reflections vector search.

    Input shape from search_tool.py for reflections:
        table=reflections
          Ch5 2022-09–2023-04 [78%]: <reflection text up to 200 chars>
          Ch10 2024-04–2024-08 [72%]: <...>

    Strategy: keep table header + first chapter result with truncated text.
    """
    body = body.strip()
    if len(body) <= 300:
        return body

    lines = body.splitlines()
    header = lines[0] if lines and lines[0].startswith("table=") else ""
    chapter_lines = [ln for ln in lines[1:] if ln.strip().startswith("Ch")]

    if not chapter_lines:
        return compress_vsearch(body)  # Fallback to generic vsearch shape.

    kept = chapter_lines[:1]
    remaining = len(chapter_lines) - 1
    suffix = f"\n  (+{remaining} more chapters)" if remaining > 0 else ""
    head = (header + "\n") if header else ""
    return head + "\n".join(kept) + suffix


# ── Registry + top-level dispatch ────────────────────────────────────────────

_COMPRESSORS: dict[str, Callable[[str], str]] = {
    "RAW-SQL":      compress_sql,
    "RAW-COMPUTED": compress_python,
    "SEMANTIC-RAW": compress_vsearch,
    "EXTERNAL":     compress_external,
    "NARRATIVE":    compress_narrative,
}


def compress_observation(content: str, fallback_chars: int = 200) -> str:
    """Compress a user-role OBSERVATION message for inclusion in trimmed history.

    `content` is the raw `msg["content"]` from `history` — typically wrapped as:
        OBSERVATION (round N/M, phase P):
        [<TAG>] <body...>

    The OBSERVATION wrapper line is preserved verbatim so the agent retains
    round-number context. The body is parsed for its `[<TAG>]` prefix, dispatched
    to the matching compressor, and re-wrapped with a `(compressed)` marker.

    On any failure (unknown tag, malformed body, compressor exception), falls
    back to `content[:fallback_chars] + " [... trimmed]"` — i.e., the current
    pre-Layer-1 behaviour. Layer 1 must never raise into _trim_history.
    """
    try:
        # Detach the OBSERVATION wrapper line, if present.
        wrapper_match = _OBS_WRAPPER_RE.match(content)
        if wrapper_match:
            header_line = wrapper_match.group(1)
            obs_text    = wrapper_match.group(2)
        else:
            header_line = ""
            obs_text    = content

        # Detect the [TAG] prefix on the observation body.
        tag_match = _TAG_RE.match(obs_text)
        if not tag_match:
            raise ValueError("no [TAG] prefix")

        tag = tag_match.group(1)
        compressor = _COMPRESSORS.get(tag)
        if compressor is None:
            raise ValueError(f"unknown tag: {tag}")

        # Strip "[TAG]" + optional leading whitespace/newline from the body.
        body = obs_text[len(f"[{tag}]"):].lstrip("\n").rstrip()
        compressed_body = compressor(body)

        # Compressor returned the body unchanged (short body, ERROR body, etc.) —
        # no point wrapping with "(compressed)"; that would make output strictly
        # longer than input. Return original content untouched.
        if compressed_body == body:
            return content

        # Defence in depth: if compression somehow failed to shrink (or made
        # the body longer), use simple truncation instead. Catches pathological
        # compressors and edge cases like malformed bodies.
        wrapped = f"[{tag}] (compressed)\n{compressed_body}"
        if len(wrapped) >= len(obs_text):
            compressed_body = body[:fallback_chars] + " [... trimmed]"
            wrapped = f"[{tag}] (compressed)\n{compressed_body}"

        return f"{header_line}\n{wrapped}" if header_line else wrapped

    except Exception:
        return content[:fallback_chars] + " [... trimmed]"


def compress_assistant(content: str, fallback_chars: int = 120) -> str:
    """Compress an assistant THOUGHT+ACTION message for inclusion in trimmed history.

    Strategy: keep the first sentence of THOUGHT + the tool name from ACTION.
    Drop the ACTION args entirely — the very next observation already implies
    what was called.

    Output shape: `THOUGHT (gist): <first sentence>. -> ACTION: <tool>`

    Falls back to first-N-chars trim on parse failure or non-standard content
    (e.g., format-error retry messages, system-injected notes).
    """
    try:
        thought_match = _THOUGHT_RE.search(content)
        action_match  = _ACTION_RE.search(content)
        if not thought_match or not action_match:
            raise ValueError("no THOUGHT/ACTION pair")

        thought = thought_match.group(1).strip()
        # First sentence: split on ". " (sentence boundary, not decimal).
        first_sentence = re.split(r"\.\s+", thought, maxsplit=1)[0].strip()
        if len(first_sentence) > 200:
            first_sentence = first_sentence[:200] + "..."

        action_json = action_match.group(1)
        tool_match = re.search(r'"tool"\s*:\s*"([^"]+)"', action_json)
        tool_name = tool_match.group(1) if tool_match else "?"

        return f"THOUGHT (gist): {first_sentence}. -> ACTION: {tool_name}"

    except Exception:
        return content[:fallback_chars] + " [... trimmed]"
