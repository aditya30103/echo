"""Integration test: Layer 1 compressors land correctly inside _react_loop.

Drives `_react_loop` end-to-end with monkeypatched llm_chat + dispatch +
_generate_rubric. Verifies that by the time the agent reaches round 8, the
llm_chat call receives a `messages` list where the early-round observations
are present in COMPRESSED form (not the original 200-char trim, not the full
output) and the most recent 4 rounds are present in FULL form.

This is the load-bearing assertion for Layer 1: `_trim_history` actually
swapped its inner branches from `[:200]` truncation to compressor dispatch,
and the agent's view of history reflects that.
"""

from typing import List

import pytest

from api.routers import speak as speak_mod


# ── Fake observation generator ───────────────────────────────────────────────
# Returns a known-long SQL observation that, raw, is ~1500 chars but compressed
# is ~150 chars. The size delta is what makes the assertion unambiguous.

def _fake_sql_obs() -> str:
    rows = "\n".join(
        f"{{'channel_name': 'channel_{i:03d}', 'n': {(i+1) * 7}}}"
        for i in range(50)
    )
    return f"[RAW-SQL]\n{rows}\n[50 rows]"


def _fake_llm_chat_factory(captured_messages: List[list]):
    """Build a fake llm_chat that captures the messages list passed in and
    returns a tool-call response. Stops at round 8 by calling finish."""

    def fake_llm_chat(messages, **_kwargs):
        captured_messages.append([dict(m) for m in messages])
        round_n = len(captured_messages)

        # Rounds 1-7: keep calling run_sql so history grows.
        if round_n < 8:
            response = (
                f"THOUGHT: Round {round_n} probing.\n"
                'ACTION: {"tool": "run_sql", "args": {"query": "SELECT * FROM watches LIMIT 1"}}'
            )
        else:
            # Round 8: call finish so the loop exits cleanly.
            response = (
                "THOUGHT: Compiling findings.\n"
                'ACTION: {"tool": "finish", "args": {'
                '"findings": [{"claim": "test claim", "evidence": "rounds 1-7", '
                '"source_tag": "RAW-SQL", "confidence": "high"}], '
                '"side_insights": []}}'
            )

        usage = {
            "input_tokens":                1000,
            "output_tokens":               80,
            "cache_read_input_tokens":     0,
            "cache_creation_input_tokens": 0,
        }
        return response, "claude-sonnet-4-6", usage, "end_turn"

    return fake_llm_chat


def test_react_loop_compresses_old_observations_keeps_recent_full(monkeypatch):
    """At round 8 with _KEEP_FULL_ROUNDS=4:
       - Rounds 1-3 observations should appear in COMPRESSED form.
       - Rounds 4-7 observations should appear in FULL form (last 4 rounds).
       - Round 1 assistant should appear in COMPRESSED form.
    """
    captured: List[list] = []

    monkeypatch.setattr(speak_mod, "llm_chat",          _fake_llm_chat_factory(captured))
    monkeypatch.setattr(speak_mod, "dispatch",          lambda *a, **k: _fake_sql_obs())
    monkeypatch.setattr(speak_mod, "_generate_rubric",  lambda *a, **k: "(stub rubric)")

    # max_rounds=30 keeps us well clear of the "rounds_left == 3" system-inject
    # at round (max_rounds-3) which would add an extra non-OBSERVATION user
    # message to history and skew the per-round counts below.
    req = speak_mod.SpeakRequest(query="test probe", max_rounds=30)
    events = list(speak_mod._react_loop(req, db=None))

    # Sanity: the loop ran 8 rounds and finished cleanly.
    finish_evt = next(e for e in events if e["type"] == "finish")
    assert finish_evt["rounds_used"] == 8
    assert finish_evt["hit_round_limit"] is False
    assert len(captured) == 8, f"expected 8 LLM calls, got {len(captured)}"

    # ── The load-bearing assertion: inspect the messages list at round 8 ──
    # captured[7] is the messages list passed to llm_chat on the FINAL round.
    # By then history has: [query, assistant_R1, obs_R1, ..., assistant_R7, obs_R7]
    # = 1 + 2*7 = 15 messages. _trim_history keeps:
    #   - index 0 (query) full
    #   - cutoff = 15 - 4*2 = 7 → indices 7..14 kept full (the last 4 rounds)
    #   - indices 1..6 → compressed (rounds 1-3 inclusive: 1 assistant + 1 obs per round)
    #
    # cutoff math (current implementation, len(history)=15, keep_full=4):
    #   cutoff = max(1, 15 - 8) = 7
    # So indices 0, 7, 8, 9, 10, 11, 12, 13, 14 are kept full; 1..6 are compressed.

    round_8_messages = captured[7]

    # System message is prepended by _react_loop; user messages follow.
    user_msgs      = [m for m in round_8_messages if m["role"] == "user"]
    assistant_msgs = [m for m in round_8_messages if m["role"] == "assistant"]

    # First user message is the original query — must be intact.
    assert user_msgs[0]["content"] == "test probe"

    # Find compressed observations (those carry the "(compressed)" marker that
    # compress_observation injects into the body).
    compressed_obs   = [m for m in user_msgs if "(compressed)" in m["content"]]
    full_obs         = [m for m in user_msgs[1:] if "(compressed)" not in m["content"]]
    compressed_asst  = [m for m in assistant_msgs if "THOUGHT (gist):" in m["content"]]
    full_asst        = [m for m in assistant_msgs if "THOUGHT (gist):" not in m["content"]]

    # Rounds 1-3 observations compressed → 3 compressed user messages.
    # Rounds 4-7 observations full → 4 full user messages.
    assert len(compressed_obs) == 3, (
        f"expected 3 compressed observations (rounds 1-3), got {len(compressed_obs)}"
    )
    assert len(full_obs) == 4, (
        f"expected 4 full observations (rounds 4-7), got {len(full_obs)}"
    )

    # Same shape for assistant messages.
    assert len(compressed_asst) == 3, (
        f"expected 3 compressed assistant messages (rounds 1-3), got {len(compressed_asst)}"
    )
    assert len(full_asst) == 4, (
        f"expected 4 full assistant messages (rounds 4-7), got {len(full_asst)}"
    )

    # Verify compression actually shrinks: compressed obs much shorter than full obs.
    avg_compressed_size = sum(len(m["content"]) for m in compressed_obs) / len(compressed_obs)
    avg_full_size       = sum(len(m["content"]) for m in full_obs)       / len(full_obs)
    assert avg_compressed_size < avg_full_size / 3, (
        f"compression should shrink obs by ≥3x; "
        f"avg compressed={avg_compressed_size:.0f}, avg full={avg_full_size:.0f}"
    )

    # Spot-check compressed-SQL structure: must include 'cols:' and 'first:' lines.
    sample = compressed_obs[0]["content"]
    assert "[RAW-SQL] (compressed)" in sample
    assert "cols: channel_name, n" in sample
    assert "first:" in sample
    assert "last:" in sample
    assert "[50 rows]" in sample
