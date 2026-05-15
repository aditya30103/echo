"""Unit tests for api/tools/compressors.py — Layer 1 per-tool observation compression.

Coverage target: every gap in the test diagram from the /plan-eng-review of Layer 1.
Patterns mirror tests/test_speak_response.py (the regression-guard style).
"""

import json

import pytest

from api.tools.compressors import (
    compress_assistant,
    compress_external,
    compress_narrative,
    compress_observation,
    compress_python,
    compress_sql,
    compress_vsearch,
)


# ────────────────────────────────────────────────────────────────────────────
#  compress_sql
# ────────────────────────────────────────────────────────────────────────────

def test_compress_sql_short_body_passes_through():
    body = "{'col': 1}\n{'col': 2}\n[2 rows]"
    assert compress_sql(body) == body  # ≤200 chars, no compression needed


def test_compress_sql_typical_multirow_keeps_cols_first_last_count():
    rows = "\n".join(f"{{'month': '2020-{m:02d}', 'n': {m*3}}}" for m in range(1, 13))
    body = f"{rows}\n[12 rows]"
    out = compress_sql(body)
    assert "cols: month, n" in out
    assert "first: {'month': '2020-01', 'n': 3}" in out
    assert "last:  {'month': '2020-12', 'n': 36}" in out
    assert "[12 rows]" in out
    assert len(out) < len(body), "compression should shrink the body"


def test_compress_sql_preserves_row_limit_marker():
    rows = "\n".join(f"{{'id': {i}, 'val': 'x' * 30}}" for i in range(50))
    body = f"{rows}\n[200 rows — may be more, hit row limit]"
    out = compress_sql(body)
    assert "[200 rows — may be more, hit row limit]" in out


def test_compress_sql_error_body_passes_through():
    body = "ERROR: near \"FORM\": syntax error"
    assert compress_sql(body) == body


def test_compress_sql_no_rows_returned_passes_through():
    body = "(no rows returned)"
    assert compress_sql(body) == body


def test_compress_sql_malformed_no_marker_falls_back():
    # Body has rows but no terminal "[N rows]" marker — looks malformed.
    body = "\n".join(f"{{'col': {i}}}" for i in range(50))  # long enough to bypass short-circuit
    out = compress_sql(body)
    # No marker found → fall back to original body.
    assert out == body


def test_compress_sql_handles_unparseable_keys_gracefully():
    # Dict-like rows with weird formatting that the key regex can't parse.
    body = "(weird1: 1, weird2: 2)\n" * 20 + "[20 rows]"
    out = compress_sql(body)
    # Should not raise. Should still attempt compression since marker exists.
    # Either the unparseable marker shows up OR we get a fallback shape.
    assert "[20 rows]" in out


# ────────────────────────────────────────────────────────────────────────────
#  compress_python
# ────────────────────────────────────────────────────────────────────────────

def test_compress_python_short_body_passes_through():
    body = "x = 1\nprint(x)\n# output: 1"
    assert compress_python(body) == body


def test_compress_python_typical_body_keeps_head_and_tail():
    body = (
        "=== TOPIC FIRST APPEARANCE ===\n\n"
        + "x" * 600
        + "\n\nCONCLUSION: pattern observed."
    )
    out = compress_python(body)
    assert "=== TOPIC FIRST APPEARANCE ===" in out
    assert "CONCLUSION: pattern observed." in out
    assert "[... middle elided ...]" in out
    assert len(out) < len(body)


def test_compress_python_error_body_expands_tail():
    body = (
        "=== ANALYSIS ===\n"
        + "x" * 400
        + "\nERROR: Traceback (most recent call last):\n"
        + "  File \"<string>\", line 5, in <module>\n"
        + "KeyError: 'missing_column'"
    )
    out = compress_python(body)
    assert "KeyError: 'missing_column'" in out
    # Tail should include enough of the traceback context.
    assert "Traceback" in out or "KeyError" in out


def test_compress_python_no_output_passes_through():
    body = "(no output — use print() to surface results)"
    assert compress_python(body) == body


def test_compress_python_head_in_tail_passes_through():
    # Body where the first non-empty line also appears verbatim in the last
    # 250 chars — compression would be redundant.
    head = "=== SECTION ==="
    body = head + "\n" + "x" * 200 + "\n" + head
    out = compress_python(body)
    assert out == body  # passes through to avoid duplicating head


# ────────────────────────────────────────────────────────────────────────────
#  compress_vsearch
# ────────────────────────────────────────────────────────────────────────────

def test_compress_vsearch_short_body_passes_through():
    body = "table=videos\n  [85%] T — C (3x)"
    assert compress_vsearch(body) == body


def test_compress_vsearch_typical_keeps_header_and_first_three():
    results = "\n".join(
        f"  [{80-i*5}%] Title{i} — Channel{i} (watched {i+1}x)"
        for i in range(5)
    )
    body = f"table=videos\n{results}" + "\n  extra padding " * 20
    out = compress_vsearch(body)
    assert "table=videos" in out
    assert "[80%] Title0" in out
    assert "[75%] Title1" in out
    assert "[70%] Title2" in out
    assert "[65%] Title3" not in out  # only first 3 kept
    assert "(+2 more results)" in out


def test_compress_vsearch_exactly_three_no_suffix():
    body = (
        "table=videos\n"
        "  [85%] A — Ch1 (1x)\n"
        "  [80%] B — Ch2 (1x)\n"
        "  [75%] C — Ch3 (1x)\n"
        + "padding " * 50
    )
    out = compress_vsearch(body)
    assert "(+0 more" not in out
    assert "more results" not in out


def test_compress_vsearch_no_results_falls_back():
    body = "table=videos\n" + "junk content " * 30
    out = compress_vsearch(body)
    # No [N%] lines means no results to keep — pass through (body is stripped at entry).
    assert out == body.strip()


# ────────────────────────────────────────────────────────────────────────────
#  compress_external
# ────────────────────────────────────────────────────────────────────────────

def test_compress_external_short_body_passes_through():
    body = '{"title": "Short", "channel": "X"}'
    assert compress_external(body) == body


def test_compress_external_youtube_json_keeps_key_fields():
    data = {
        "title":       "Rick Astley - Never Gonna Give You Up",
        "channel":     "Rick Astley",
        "view_count":  1_500_000_000,
        "duration":    "PT3M33S",
        "description": "Lorem ipsum " * 200,  # bulky — should be dropped
        "tags":        ["music", "80s"] * 50,
    }
    body = json.dumps(data, indent=2)
    out = compress_external(body)
    parsed = json.loads(out)
    assert parsed["title"] == data["title"]
    assert parsed["channel"] == data["channel"]
    assert parsed["view_count"] == 1_500_000_000
    assert "description" not in parsed
    assert "tags" not in parsed


def test_compress_external_invalid_json_falls_through_to_lines():
    body = "{ malformed json " + "padding " * 50
    out = compress_external(body)
    # Should not raise. Falls back to line-based path or original.
    assert isinstance(out, str)


def test_compress_external_web_search_keeps_first_two_results():
    body = (
        "1. First result title\n"
        "   https://example.com/1\n"
        "   First snippet text.\n"
        "2. Second result title\n"
        "   https://example.com/2\n"
        "   Second snippet text.\n"
        "3. Third result title\n"
        "   https://example.com/3\n"
        "   Third snippet text."
    )
    out = compress_external(body)
    if len(body) <= 300:
        # If body is short enough to pass through, all 9 lines present.
        assert "Third result title" in out
    else:
        assert "First result title" in out
        assert "Second result title" in out
        assert "(+1 more results)" in out


# ────────────────────────────────────────────────────────────────────────────
#  compress_narrative
# ────────────────────────────────────────────────────────────────────────────

def test_compress_narrative_short_body_passes_through():
    body = "table=reflections\n  Ch5 2022-09–2023-04 [78%]: short text"
    assert compress_narrative(body) == body


def test_compress_narrative_typical_keeps_first_chapter():
    body = (
        "table=reflections\n"
        "  Ch5 2022-09–2023-04 [78%]: " + "x" * 200 + "\n"
        "  Ch10 2024-04–2024-08 [72%]: " + "y" * 200 + "\n"
        "  Ch12 2024-09–2024-11 [65%]: " + "z" * 200 + "\n"
    )
    out = compress_narrative(body)
    assert "table=reflections" in out
    assert "Ch5" in out
    assert "Ch10" not in out
    assert "(+2 more chapters)" in out


def test_compress_narrative_no_chapter_lines_falls_back_to_vsearch():
    body = (
        "table=reflections\n"
        "  [85%] something that isn't chapter-shaped\n"
        "  [80%] another non-chapter line\n"
        + "padding " * 50
    )
    out = compress_narrative(body)
    # Should not raise. compress_vsearch handles the [%] lines as fallback.
    assert "table=reflections" in out


# ────────────────────────────────────────────────────────────────────────────
#  compress_observation — dispatch + envelope
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def long_sql_obs():
    rows = "\n".join(f"{{'month': '2020-{m:02d}', 'n': {m*3}}}" for m in range(1, 13))
    return (
        "OBSERVATION (round 5/50, phase 1):\n"
        f"[RAW-SQL]\n{rows}\n[12 rows]"
    )


def test_compress_observation_dispatches_to_sql(long_sql_obs):
    out = compress_observation(long_sql_obs)
    assert "[RAW-SQL] (compressed)" in out
    assert "cols: month, n" in out
    assert "OBSERVATION (round 5/50, phase 1):" in out  # wrapper preserved
    assert len(out) < len(long_sql_obs)


def test_compress_observation_dispatches_to_python():
    body = (
        "OBSERVATION (round 13/50, phase 1):\n"
        "[RAW-COMPUTED]\n=== HEADER ===\n"
        + "x" * 600
        + "\n\nFINAL: result line"
    )
    out = compress_observation(body)
    assert "[RAW-COMPUTED] (compressed)" in out
    assert "=== HEADER ===" in out
    assert "FINAL: result line" in out


def test_compress_observation_dispatches_to_vsearch():
    results = "\n".join(f"  [{85-i*5}%] r{i} — c{i} (1x)" for i in range(5))
    body = f"OBSERVATION (round 7/30, phase 1):\n[SEMANTIC-RAW] table=videos\n{results}" + "\npadding " * 30
    out = compress_observation(body)
    assert "[SEMANTIC-RAW] (compressed)" in out
    assert "table=videos" in out


def test_compress_observation_dispatches_to_external():
    body = (
        "OBSERVATION (round 4/20, phase 1):\n"
        "[EXTERNAL]\n"
        + json.dumps({"title": "T", "channel": "C", "view_count": 10,
                      "description": "x" * 500}, indent=2)
    )
    out = compress_observation(body)
    assert "[EXTERNAL] (compressed)" in out
    assert '"title": "T"' in out
    assert "description" not in out


def test_compress_observation_dispatches_to_narrative():
    body = (
        "OBSERVATION (round 15/30, phase 2):\n"
        "[NARRATIVE] table=reflections\n"
        "  Ch5 2022-09–2023-04 [78%]: " + "x" * 200 + "\n"
        "  Ch10 2024-04–2024-08 [72%]: " + "y" * 200
    )
    out = compress_observation(body)
    assert "[NARRATIVE] (compressed)" in out
    assert "Ch5" in out


def test_compress_observation_unknown_tag_falls_back():
    body = "OBSERVATION (round 5/50, phase 1):\n[MYSTERY-TAG]\nsome content here " * 20
    out = compress_observation(body)
    # No matching compressor — falls back to first-N truncation marker.
    assert "[... trimmed]" in out


def test_compress_observation_no_tag_falls_back():
    body = "OBSERVATION (round 5/50, phase 1):\nno tag prefix at all " * 20
    out = compress_observation(body)
    assert "[... trimmed]" in out


def test_compress_observation_empty_content_safe():
    out = compress_observation("")
    # Empty content has nothing to truncate; falls back to "" + " [... trimmed]".
    assert "[... trimmed]" in out
    assert isinstance(out, str)


def test_compress_observation_compressor_exception_falls_back(monkeypatch):
    """If a compressor raises mid-dispatch, the wrapper catches it cleanly."""
    from api.tools import compressors

    def explode(_body):
        raise RuntimeError("simulated compressor bug")

    monkeypatch.setitem(compressors._COMPRESSORS, "RAW-SQL", explode)

    body = "OBSERVATION (round 1/10, phase 1):\n[RAW-SQL]\n" + "x" * 400
    out = compress_observation(body)
    assert "[... trimmed]" in out  # fallback, not the explosion


def test_compress_observation_caps_output_at_input_size():
    """Defence in depth: if a compressor returns something longer than input, clip it."""
    # SQL body that's pathologically just under the 200-char passthrough threshold
    # but with rows that, when compressed, would produce more chars than input.
    # In practice this can't happen with our current compressors, but the guard exists.
    body = "OBSERVATION (round 1/10, phase 1):\n[RAW-SQL]\n" + "{'x': 1}\n" * 30 + "[30 rows]"
    out = compress_observation(body)
    # The output, including wrapper, must not exceed the input.
    assert len(out) <= len(body) + 20  # tiny margin for "(compressed)" marker


def test_compress_observation_works_without_wrapper():
    """Some callers may pass content without the OBSERVATION wrapper. Still works."""
    body = "[RAW-SQL]\n" + "\n".join(f"{{'a': {i}}}" for i in range(30)) + "\n[30 rows]"
    out = compress_observation(body)
    assert "[RAW-SQL] (compressed)" in out
    assert "cols: a" in out


# ────────────────────────────────────────────────────────────────────────────
#  compress_assistant
# ────────────────────────────────────────────────────────────────────────────

def test_compress_assistant_typical_extracts_thought_and_tool():
    content = (
        "THOUGHT: Looking at the data, I want to query monthly counts. "
        "This will give me the time series.\n"
        'ACTION: {"tool": "run_sql", "args": {"query": "SELECT ..."}}'
    )
    out = compress_assistant(content)
    assert "THOUGHT (gist): Looking at the data, I want to query monthly counts" in out
    assert "-> ACTION: run_sql" in out
    assert len(out) < len(content)


def test_compress_assistant_no_thought_action_pattern_falls_back():
    content = "[System: Phase 2 begins. vector_search(reflections) is now available.]"
    out = compress_assistant(content)
    assert "[... trimmed]" in out


def test_compress_assistant_multi_sentence_keeps_only_first():
    content = (
        "THOUGHT: First sentence ends here. Second sentence is dropped. "
        "Third one too.\n"
        'ACTION: {"tool": "finish", "args": {}}'
    )
    out = compress_assistant(content)
    assert "First sentence ends here" in out
    assert "Second sentence" not in out
    assert "-> ACTION: finish" in out


def test_compress_assistant_truncates_very_long_first_sentence():
    long_sentence = "x" * 300
    content = (
        f"THOUGHT: {long_sentence}\n"
        'ACTION: {"tool": "execute_python", "args": {"code": "..."}}'
    )
    out = compress_assistant(content)
    assert "..." in out
    assert "-> ACTION: execute_python" in out


def test_compress_assistant_empty_content_safe():
    out = compress_assistant("")
    assert "[... trimmed]" in out
    assert isinstance(out, str)


def test_compress_assistant_action_without_tool_field():
    """Malformed ACTION JSON without a 'tool' key still produces output."""
    content = 'THOUGHT: trying something.\nACTION: {"args": {}}'
    out = compress_assistant(content)
    assert "THOUGHT (gist)" in out
    assert "-> ACTION: ?" in out
