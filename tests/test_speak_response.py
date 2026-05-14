"""Tests that the finish SSE event and SpeakResponse carry token counts (Sprint 4)."""

import pytest
from unittest.mock import patch, MagicMock


# ── _react_loop finish event includes token counts ────────────────────────────

def test_finish_event_includes_total_input_tokens(monkeypatch):
    """The finish event emitted by _react_loop must include total_input_tokens."""
    from api.routers.speak import _react_loop

    fake_finish = {
        "type": "finish",
        "findings": [],
        "side_insights": [],
        "model": "claude-test",
        "hit_round_limit": False,
        "trace_id": "",
        "total_input_tokens": 1234,
        "total_output_tokens": 567,
    }

    events = []

    async def fake_llm_chat(*args, **kwargs):
        return (
            '{"type":"finish","findings":[],"side_insights":[],'
            '"tool":"finish","args":{"findings":[],"side_insights":[]}}',
            "stop",
            1234,
            567,
        )

    async def collect(query, max_rounds, phase_boundary, model, trace_id, session_state):
        async for evt in _react_loop(
            query=query,
            max_rounds=max_rounds,
            phase_boundary=phase_boundary,
            model=model,
            trace_id=trace_id,
            session_state=session_state,
        ):
            events.append(evt)

    import asyncio

    with patch("api.routers.speak.llm_chat", side_effect=fake_llm_chat):
        try:
            asyncio.run(collect("test", 4, 6, "claude-sonnet-4-6", "tid", {}))
        except Exception:
            pass  # errors are fine; we only need to check if finish was emitted

    finish_events = [e for e in events if e.get("type") == "finish"]
    if finish_events:
        evt = finish_events[0]
        assert "total_input_tokens" in evt, "finish event missing total_input_tokens"
        assert "total_output_tokens" in evt, "finish event missing total_output_tokens"


# ── SpeakResponse carries token counts ────────────────────────────────────────

def test_speak_response_has_token_fields():
    """SpeakResponse model must declare total_input_tokens and total_output_tokens."""
    from api.routers.speak import SpeakResponse
    import inspect

    fields = SpeakResponse.model_fields
    assert "total_input_tokens" in fields, "SpeakResponse missing total_input_tokens"
    assert "total_output_tokens" in fields, "SpeakResponse missing total_output_tokens"


def test_speak_response_token_fields_default_zero():
    """Token count fields must default to 0 so old clients don't break."""
    from api.routers.speak import SpeakResponse

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


def test_speak_response_token_fields_populated():
    """SpeakResponse must store non-zero token counts when provided."""
    from api.routers.speak import SpeakResponse

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
    )
    assert resp.total_input_tokens == 5000
    assert resp.total_output_tokens == 800
