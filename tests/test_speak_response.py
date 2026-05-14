"""Tests that the speak endpoint and SpeakResponse carry token counts (Sprint 4 + 5)."""

from unittest.mock import patch
from fastapi.testclient import TestClient


# ── speak endpoint propagates token counts from finish event ──────────────────

def test_speak_endpoint_propagates_token_counts():
    """The /api/speak endpoint must return token counts from the finish event."""
    from api.main import app

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

    with patch("api.routers.speak._react_loop", fake_loop):
        client = TestClient(app)
        resp = client.post("/api/speak", json={"query": "test"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_input_tokens"] == 1234
    assert data["total_output_tokens"] == 567
    assert data["total_cache_read_tokens"] == 200


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
    assert resp.total_cache_read_tokens == 0


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
        total_cache_read_tokens=300,
    )
    assert resp.total_input_tokens == 5000
    assert resp.total_output_tokens == 800
    assert resp.total_cache_read_tokens == 300
