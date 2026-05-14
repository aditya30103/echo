"""Tests for _validate_findings() in api/routers/speak.py.

Covers the EXTERNAL tag branch added in Sprint 3, regression guards for
existing tags, and the unknown-tag fallback to narrative.
"""

import pytest
from api.routers.speak import _validate_findings


def _make(tag: str, confidence: str = "high") -> dict:
    return {
        "claim": "test claim",
        "evidence": "test evidence",
        "source_tag": tag,
        "confidence": confidence,
    }


# ── EXTERNAL tag ──────────────────────────────────────────────────────────────

def test_external_narrative_derived_false():
    findings = _validate_findings([_make("EXTERNAL")])
    assert len(findings) == 1
    assert findings[0].narrative_derived is False


def test_external_is_side_insight_true():
    findings = _validate_findings([_make("EXTERNAL")])
    assert findings[0].is_side_insight is True


def test_external_confidence_forced_medium():
    """EXTERNAL findings always get confidence=medium regardless of what the LLM said."""
    findings = _validate_findings([_make("EXTERNAL", confidence="high")])
    assert findings[0].confidence == "medium"


def test_external_claim_preserved():
    raw = [{"claim": "video title says X", "evidence": "lookup result", "source_tag": "EXTERNAL", "confidence": "high"}]
    findings = _validate_findings(raw)
    assert findings[0].claim == "video title says X"


# ── RAW-SQL tag ───────────────────────────────────────────────────────────────

def test_raw_sql_narrative_derived_false():
    findings = _validate_findings([_make("RAW-SQL")])
    assert findings[0].narrative_derived is False


def test_raw_sql_is_side_insight_false():
    findings = _validate_findings([_make("RAW-SQL")])
    assert findings[0].is_side_insight is False


def test_raw_sql_confidence_preserved():
    findings = _validate_findings([_make("RAW-SQL", confidence="low")])
    assert findings[0].confidence == "low"


# ── RAW-COMPUTED tag ──────────────────────────────────────────────────────────

def test_raw_computed_narrative_derived_false():
    findings = _validate_findings([_make("RAW-COMPUTED")])
    assert findings[0].narrative_derived is False


def test_raw_computed_is_side_insight_false():
    findings = _validate_findings([_make("RAW-COMPUTED")])
    assert findings[0].is_side_insight is False


# ── SEMANTIC-RAW tag ──────────────────────────────────────────────────────────

def test_semantic_raw_narrative_derived_false():
    findings = _validate_findings([_make("SEMANTIC-RAW")])
    assert findings[0].narrative_derived is False


def test_semantic_raw_is_side_insight_false():
    findings = _validate_findings([_make("SEMANTIC-RAW")])
    assert findings[0].is_side_insight is False


# ── NARRATIVE / unknown tag fallback ─────────────────────────────────────────

def test_narrative_tag_narrative_derived_true():
    findings = _validate_findings([_make("NARRATIVE")])
    assert findings[0].narrative_derived is True


def test_unknown_tag_narrative_derived_true():
    findings = _validate_findings([_make("COMPLETELY-UNKNOWN-TAG")])
    assert findings[0].narrative_derived is True


def test_unknown_tag_confidence_low():
    findings = _validate_findings([_make("UNKNOWN", confidence="high")])
    assert findings[0].confidence == "low"


# ── mixed batch ───────────────────────────────────────────────────────────────

def test_mixed_batch_preserves_order_and_count():
    raw = [
        _make("RAW-SQL"),
        _make("EXTERNAL"),
        _make("SEMANTIC-RAW"),
        _make("NARRATIVE"),
    ]
    findings = _validate_findings(raw)
    assert len(findings) == 4
    assert findings[0].narrative_derived is False
    assert findings[1].is_side_insight is True
    assert findings[2].narrative_derived is False
    assert findings[3].narrative_derived is True


def test_empty_list_returns_empty():
    assert _validate_findings([]) == []
