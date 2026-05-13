"""Tests for api/routers/diff.py:_build_prompt() — pure formatting function."""

from api.routers.diff import _build_prompt


def _ch(overrides=None):
    base = {
        "id": 1,
        "label": "Test Chapter",
        "start_at": "2020-01-01T00:00:00",
        "end_at": "2020-06-30T23:59:59",
        "night_ratio": 0.35,
        "modal_hour": 23,
        "long_form_ratio": 0.6,
        "shorts_ratio": 0.05,
        "channel_density_score": 0.4,
        "median_duration_seconds": 1200,
        "top_categories": {"Education": 45, "Technology": 30},
        "reflection": "This chapter was a turning point.",
    }
    if overrides:
        base.update(overrides)
    return base


def test_prompt_contains_chapter_ids():
    prompt = _build_prompt(_ch({"id": 3}), _ch({"id": 7}))
    assert "Chapter 3" in prompt
    assert "Chapter 7" in prompt


def test_prompt_contains_period_dates():
    prompt = _build_prompt(_ch(), _ch())
    assert "2020-01-01" in prompt


def test_prompt_contains_night_ratio():
    prompt = _build_prompt(_ch({"night_ratio": 0.42}), _ch())
    assert "42%" in prompt


def test_prompt_contains_top_categories():
    prompt = _build_prompt(_ch({"top_categories": {"Philosophy": 70}}), _ch())
    assert "Philosophy" in prompt


def test_prompt_handles_missing_reflection():
    prompt = _build_prompt(_ch({"reflection": None}), _ch())
    assert "(no reflection yet)" in prompt


def test_prompt_handles_zero_median_duration():
    prompt = _build_prompt(_ch({"median_duration_seconds": 0}), _ch())
    assert "unknown" in prompt
