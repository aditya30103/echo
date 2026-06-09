"""Tests that the speak endpoint and SpeakResponse carry token counts (Sprint 4 + 5)."""

import json
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


# ── speak endpoint propagates token counts from finish event ──────────────────

def test_speak_endpoint_propagates_token_counts():
    """The /api/speak endpoint must return token counts from the finish event."""
    from echo.api.main import app
    from echo.api.db import get_db

    def fake_loop(req, db):
        yield {
            "type": "finish",
            "findings": [],
            "side_insights": [],
            "rounds_used": 1,
            "model": "claude-sonnet-4-6",
            "hit_round_limit": False,
            "trace_id": "test-trace",
            "total_input_tokens": 1234,
            "total_output_tokens": 567,
            "total_cache_read_tokens": 200,
        }

    # Override the get_db dependency so FastAPI doesn't try to open a real
    # SQLite file - on a fresh machine (e.g. CI) ~/.echo/echo.db doesn't exist
    # yet, so the default get_db raises OperationalError. The endpoint's
    # behavior under test (token-count propagation) doesn't touch the DB.
    app.dependency_overrides[get_db] = lambda: MagicMock()

    try:
        with patch("echo.api.routers.speak._react_loop", fake_loop):
            client = TestClient(app)
            resp = client.post("/api/speak", json={"query": "test"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_input_tokens"] == 1234
    assert data["total_output_tokens"] == 567
    assert data["total_cache_read_tokens"] == 200


# ── SpeakResponse carries token counts ────────────────────────────────────────

def test_speak_response_has_token_fields():
    """SpeakResponse model must declare total_input_tokens and total_output_tokens."""
    from echo.api.routers.speak import SpeakResponse
    import inspect

    fields = SpeakResponse.model_fields
    assert "total_input_tokens" in fields, "SpeakResponse missing total_input_tokens"
    assert "total_output_tokens" in fields, "SpeakResponse missing total_output_tokens"


def test_speak_response_token_fields_default_zero():
    """Token count fields must default to 0 so old clients don't break."""
    from echo.api.routers.speak import SpeakResponse

    resp = SpeakResponse(
        query="test",
        findings=[],
        side_insights=[],
        trace=[],
        model="claude-sonnet-4-6",
        rounds_used=0,
        hit_round_limit=False,
    )
    assert resp.total_input_tokens == 0
    assert resp.total_output_tokens == 0
    assert resp.total_cache_read_tokens == 0


def test_speak_response_token_fields_populated():
    """SpeakResponse must store non-zero token counts when provided."""
    from echo.api.routers.speak import SpeakResponse

    resp = SpeakResponse(
        query="test",
        findings=[],
        side_insights=[],
        trace=[],
        model="claude-sonnet-4-6",
        rounds_used=3,
        hit_round_limit=False,
        total_input_tokens=5000,
        total_output_tokens=800,
        total_cache_read_tokens=300,
    )
    assert resp.total_input_tokens == 5000
    assert resp.total_output_tokens == 800
    assert resp.total_cache_read_tokens == 300


# ── Layer 0: rounds_used must reflect reality on exception-break ──────────────
# Regression guard for the bug where the loop's exception handler would break
# out and the limit-branch reported req.max_rounds as rounds_used regardless
# of where the loop actually stopped (caused trace 9 to read "50/50 hit_limit"
# when the real cause was an Anthropic API timeout at round 46).

def test_react_loop_reports_actual_round_on_exception_break(monkeypatch):
    """When llm_chat raises mid-run, rounds_used = round reached, hit_limit = False."""
    from echo.api.routers import speak as speak_mod

    # call_count tracks ReAct-loop llm_chat calls only — the rubric generator
    # is mocked out separately so it doesn't consume an iteration.
    call_count = {"n": 0}

    def fake_llm_chat(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return (
                'THOUGHT: looking around\nACTION: {"tool": "run_sql", "args": {"query": "SELECT 1"}}',
                "claude-sonnet-4-6",
                {"input_tokens": 100, "output_tokens": 30,
                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                "end_turn",
            )
        raise TimeoutError("simulated Anthropic API timeout")

    monkeypatch.setattr(speak_mod, "llm_chat",          fake_llm_chat)
    monkeypatch.setattr(speak_mod, "dispatch",          lambda *a, **k: "[RAW-SQL]\n{'one': 1}\n[1 rows]")
    monkeypatch.setattr(speak_mod, "_generate_rubric",  lambda *a, **k: "(stub rubric)")

    req = speak_mod.SpeakRequest(query="probe", max_rounds=10)

    # Drive the generator end-to-end and capture the terminal finish event.
    events = list(speak_mod._react_loop(req, db=None))
    finish = next(e for e in events if e["type"] == "finish")

    assert finish["rounds_used"]      == 2,  "should report round 2 (where it crashed), not max_rounds"
    assert finish["hit_round_limit"]  is False, "exception-break is not hitting the round cap"
    assert "round 2/10" in finish["side_insights"][0]
    assert "simulated" in finish["side_insights"][0].lower()

    error_evts = [e for e in events if e["type"] == "error"]
    assert len(error_evts) == 1
    assert error_evts[0]["round"] == 2


def test_react_loop_natural_completion_reports_max_rounds(monkeypatch):
    """When the loop runs out of rounds without finish, hit_limit=True, rounds_used=max."""
    from echo.api.routers import speak as speak_mod

    def fake_llm_chat(*_args, **_kwargs):
        # Never finish; keep calling a tool every round.
        return (
            'THOUGHT: still looking\nACTION: {"tool": "run_sql", "args": {"query": "SELECT 1"}}',
            "claude-sonnet-4-6",
            {"input_tokens": 50, "output_tokens": 20,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            "end_turn",
        )

    monkeypatch.setattr(speak_mod, "llm_chat",          fake_llm_chat)
    monkeypatch.setattr(speak_mod, "dispatch",          lambda *a, **k: "[RAW-SQL]\nrow")
    monkeypatch.setattr(speak_mod, "_generate_rubric",  lambda *a, **k: "(stub rubric)")

    req = speak_mod.SpeakRequest(query="probe", max_rounds=3)
    finish = next(e for e in speak_mod._react_loop(req, db=None) if e["type"] == "finish")

    assert finish["rounds_used"]     == 3
    assert finish["hit_round_limit"] is True
    assert "3-round limit" in finish["side_insights"][0]


# ── Happy path: tool round → finish with validated findings ───────────────────
# The two tests above exercise failure modes (crash, round-limit). This covers the
# success path the agent is actually for: parse ACTION → dispatch a real tool →
# thread the observation into the next round → finish with structured findings.

def test_react_loop_happy_path_threads_observation_and_returns_findings(monkeypatch):
    from echo.api.routers import speak as speak_mod

    captured_messages = []
    calls = {"n": 0}

    def fake_llm_chat(messages, *_args, **_kwargs):
        calls["n"] += 1
        captured_messages.append(messages)
        usage = {"input_tokens": 80, "output_tokens": 15,
                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        if calls["n"] == 1:
            return (
                'THOUGHT: count the watches\n'
                'ACTION: {"tool": "run_sql", "args": {"query": "SELECT COUNT(*) FROM watches"}}',
                "claude-sonnet-4-6", usage, "end_turn",
            )
        finish_action = {
            "tool": "finish",
            "args": {
                "findings": [{
                    "claim": "You watched 6280 videos",
                    "evidence": "round 1: COUNT(*) returned 6280",
                    "source_tag": "RAW-SQL", "confidence": "high",
                }],
                "side_insights": ["a smaller observation"],
            },
        }
        return ('THOUGHT: synthesize\nACTION: ' + json.dumps(finish_action),
                "claude-sonnet-4-6", usage, "end_turn")

    monkeypatch.setattr(speak_mod, "llm_chat", fake_llm_chat)
    monkeypatch.setattr(speak_mod, "dispatch",
                        lambda *a, **k: "[RAW-SQL]\ncount\n6280\n[1 rows]")
    monkeypatch.setattr(speak_mod, "_generate_rubric", lambda *a, **k: "(stub rubric)")

    req = speak_mod.SpeakRequest(query="how many videos?", max_rounds=10)
    events = list(speak_mod._react_loop(req, db=None))

    finish = next(e for e in events if e["type"] == "finish")
    assert finish["rounds_used"] == 2
    assert finish["hit_round_limit"] is False
    assert finish["side_insights"] == ["a smaller observation"]

    # findings validated: RAW-SQL is a primary (non-side-insight) finding.
    assert len(finish["findings"]) == 1
    f = finish["findings"][0]
    assert f["claim"] == "You watched 6280 videos"
    assert f["source_tag"] == "RAW-SQL"
    assert f["confidence"] == "high"
    assert f["is_side_insight"] is False

    # the round-1 observation must be threaded into round-2's prompt — the loop
    # carries state forward, it doesn't restart each round.
    round2_user_text = " ".join(
        m["content"] for m in captured_messages[1] if m["role"] == "user"
    )
    assert "6280" in round2_user_text

    # a dispatch observation event was surfaced with its source tag.
    obs = [e for e in events if e["type"] == "observation"]
    assert len(obs) == 1 and obs[0]["source_tag"] == "RAW-SQL"


def test_react_loop_recovers_from_malformed_action(monkeypatch):
    """A round with unparseable ACTION yields a format_error and the loop continues,
    rather than crashing or silently dropping the round."""
    from echo.api.routers import speak as speak_mod

    calls = {"n": 0}

    def fake_llm_chat(messages, *_args, **_kwargs):
        calls["n"] += 1
        usage = {"input_tokens": 50, "output_tokens": 10,
                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        if calls["n"] == 1:
            # No ACTION block at all → _parse_response returns None.
            return ("THOUGHT: thinking out loud with no action block",
                    "claude-sonnet-4-6", usage, "end_turn")
        finish_action = {"tool": "finish", "args": {"findings": [], "side_insights": ["recovered"]}}
        return ('THOUGHT: ok\nACTION: ' + json.dumps(finish_action),
                "claude-sonnet-4-6", usage, "end_turn")

    monkeypatch.setattr(speak_mod, "llm_chat", fake_llm_chat)
    monkeypatch.setattr(speak_mod, "dispatch", lambda *a, **k: "[RAW-SQL] x")
    monkeypatch.setattr(speak_mod, "_generate_rubric", lambda *a, **k: "(stub rubric)")

    req = speak_mod.SpeakRequest(query="probe", max_rounds=10)
    events = list(speak_mod._react_loop(req, db=None))

    fmt_errors = [e for e in events if e["type"] == "format_error"]
    assert len(fmt_errors) == 1 and fmt_errors[0]["round"] == 1

    finish = next(e for e in events if e["type"] == "finish")
    assert finish["rounds_used"] == 2          # recovered and finished on round 2
    assert finish["hit_round_limit"] is False
    assert finish["side_insights"] == ["recovered"]
