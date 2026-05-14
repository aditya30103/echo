"""Tests for POST /api/speak/score-finding endpoint (Sprint 5)."""

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


def test_score_finding_happy_path():
    from api.main import app
    mock_lf = MagicMock()
    with patch("api.routers.speak.get_langfuse", return_value=mock_lf):
        client = TestClient(app)
        resp = client.post("/api/speak/score-finding", json={
            "trace_id": "trace-abc",
            "finding_index": 2,
            "value": 1.0,
        })
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock_lf.score.assert_called_once_with("trace-abc", "finding_2", 1.0, comment=None)


def test_score_finding_with_correction():
    from api.main import app
    mock_lf = MagicMock()
    with patch("api.routers.speak.get_langfuse", return_value=mock_lf):
        client = TestClient(app)
        resp = client.post("/api/speak/score-finding", json={
            "trace_id": "trace-xyz",
            "finding_index": 0,
            "value": 0.5,
            "correction": "The percentage is closer to 40%, not 60%",
        })
    assert resp.status_code == 200
    mock_lf.score.assert_called_once_with(
        "trace-xyz", "finding_0", 0.5,
        comment="The percentage is closer to 40%, not 60%",
    )


def test_score_finding_value_out_of_range_rejected():
    from api.main import app
    client = TestClient(app)
    resp = client.post("/api/speak/score-finding", json={
        "trace_id": "trace-abc",
        "finding_index": 0,
        "value": 2.0,
    })
    assert resp.status_code == 422


def test_score_finding_negative_value_rejected():
    from api.main import app
    client = TestClient(app)
    resp = client.post("/api/speak/score-finding", json={
        "trace_id": "trace-abc",
        "finding_index": 0,
        "value": -0.1,
    })
    assert resp.status_code == 422


def test_score_finding_empty_correction_sends_none_comment():
    """Empty correction string must send comment=None, not comment=''."""
    from api.main import app
    mock_lf = MagicMock()
    with patch("api.routers.speak.get_langfuse", return_value=mock_lf):
        client = TestClient(app)
        resp = client.post("/api/speak/score-finding", json={
            "trace_id": "tid",
            "finding_index": 1,
            "value": 0.0,
            "correction": "",
        })
    assert resp.status_code == 200
    mock_lf.score.assert_called_once_with("tid", "finding_1", 0.0, comment=None)


def test_score_finding_langfuse_key_format():
    """Langfuse score key must be finding_{index} — index is 0-based primary-subset position."""
    from api.main import app
    mock_lf = MagicMock()
    with patch("api.routers.speak.get_langfuse", return_value=mock_lf):
        client = TestClient(app)
        client.post("/api/speak/score-finding", json={"trace_id": "t", "finding_index": 3, "value": 0.5})
    score_call = mock_lf.score.call_args
    assert score_call[0][1] == "finding_3"
